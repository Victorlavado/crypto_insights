"""Base abstractions for connectors.

Patrón clave (R1): limiter DENTRO de retry — cada retry adquiere permit fresco.
Si el host rate-limita, debes esperar tu turno antes del próximo intento. NO es
un bug, es deliberado.

`supports_project(p) -> bool` debe ser predicado puro sobre propiedad técnica
del proyecto (chain, contract) — NO consultar archetype (R16: archetype es
decisión de fusion, no de connector).
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Protocol, runtime_checkable

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..models import Project, SourceSnapshot


class ConnectorError(Exception):
    """Levantada por connectors cuando el fetch falla de forma no-recuperable.

    Errores recuperables (429, 5xx, timeout) son gestionados por tenacity y
    NO levantan ConnectorError — son retried internamente.
    """

    def __init__(self, source: str, project_symbol: str, message: str) -> None:
        self.source = source
        self.project_symbol = project_symbol
        super().__init__(f"[{source}] {project_symbol}: {message}")


@runtime_checkable
class Connector(Protocol):
    """Interfaz mínima de un connector.

    Cada connector concreto declara su `source` como ClassVar y un `limiter`
    de aiolimiter dimensionado al rate limit del endpoint.
    """

    source: ClassVar[str]
    limiter: AsyncLimiter

    def supports_project(self, project: Project) -> bool:
        """Predicado puro sobre chain/contract. NO consulta archetype."""
        ...

    async def fetch(self, project: Project, *, target_date: date) -> SourceSnapshot:
        """Devuelve SourceSnapshot con payload normalizado. Levanta ConnectorError on hard fail."""
        ...


def build_http_client(*, timeout_seconds: float = 30.0) -> httpx.AsyncClient:
    """Cliente httpx async con HTTP/2 y timeout sensato.

    Reuse el cliente entre connectors del mismo batch — el pipeline crea uno
    y lo inyecta. NO crear uno por request (overhead de TCP handshake).
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        http2=True,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def honor_retry_after(retry_state: RetryCallState) -> None:
    """Hook para tenacity before_sleep: si la response tiene Retry-After, esperar ese tiempo.

    Combinado con wait_exponential_jitter, tenacity respeta la cota inferior del header.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("Retry-After")
        if retry_after:
            try:
                seconds = float(retry_after)
                retry_state.next_action.sleep = max(retry_state.next_action.sleep, seconds)  # type: ignore[union-attr]
            except (TypeError, ValueError):
                pass


def _is_retryable(exc: BaseException) -> bool:
    """Retry sólo sobre errores transitorios: 429, 5xx, timeouts, network.

    NO retry sobre 4xx no-429 (Invalid symbol, bad request, auth failure) —
    son errores deterministas; reintentar quema rate limit sin valor.
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


# Estrategia de retry estándar reutilizada por todos los connectors HTTP.
DEFAULT_RETRY_KWARGS = {
    "retry": retry_if_exception(_is_retryable),
    "wait": wait_exponential_jitter(initial=1.0, max=30.0, jitter=1.0),
    "stop": stop_after_attempt(5),
    "reraise": True,
}
