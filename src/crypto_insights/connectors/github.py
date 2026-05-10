"""GitHub connector: commits/contributors últimos 30 y 90 días.

Endpoint: GET /repos/{owner}/{repo}/commits + /contributors
Auth: PAT (CI_GITHUB_TOKEN) — 5000 req/h. Sin auth: 60 req/h IP (insuficiente
para 30 proyectos × 4 requests).

Source de verdad sobre qué repo trackear: campo `github_repo: owner/repo` en
watchlist.yaml. Si no está poblado, supports_project devuelve False y el batch
saltea (algunos proyectos como BTC/ZEC no tienen un repo único significativo).

Para Fase 1 — proof of concept con 5-10 proyectos. Fase 2 expande según
feedback. La estrategia recomendada es trackear el repo "principal" (el más
activo donde reside el core protocol).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

import httpx
from aiolimiter import AsyncLimiter
from tenacity import retry

from ..config import get_settings
from ..logging_config import get_logger
from ..models import Project, SourceSnapshot
from .base import DEFAULT_RETRY_KWARGS, ConnectorError, honor_retry_after

log = get_logger(__name__)

GITHUB_BASE = "https://api.github.com"

# Mapping symbol → "owner/repo". Mantenido aquí en lugar de en watchlist.yaml
# para evitar contaminar la watchlist con detalle GitHub. Si Victor edita
# repos, este map es la fuente de verdad.
SYMBOL_TO_REPO: dict[str, str] = {
    "AAVE": "aave-dao/aave-v3-origin",
    "PENDLE": "pendle-finance/pendle-core-v2-public",
    "ENA": "ethena-labs/StakedUsde",
    "MORPHO": "morpho-org/morpho-blue",
    "JUP": "jup-ag/jupiter-cats",
    "SYRUP": "maple-labs/maple-core-v2",
    "FXN": "f-x-protocol/protocol",
    "RENDER": "rndr-network/rndr-network-docs",
    "AKT": "akash-network/node",
    "HNT": "helium/helium-program-library",
    "GRASS": "Wynd-Network/web-extension",
    "NEAR": "near/nearcore",
    "TON": "ton-blockchain/ton",
    "SUI": "MystenLabs/sui",
    "STRK": "starkware-libs/cairo",
    "TAO": "opentensor/bittensor",
    "ZEC": "zcash/zcash",
    "BTC": "bitcoin/bitcoin",
    "VIRTUAL": "Virtual-Protocol/virtuals-python",
    "VVV": "veniceai/venice",
}


class GitHubConnector:
    """Connector para commit activity + contributors.

    Free tier auth (5000 req/h con PAT) es generoso para 30 proyectos × 2
    requests/día. Sin PAT (60/h) lo dejamos como "best effort": connector
    salta con warning en lugar de fail si no hay token.
    """

    source: ClassVar[str] = "github"

    def __init__(self, client: httpx.AsyncClient, *, rate_per_minute: int = 60) -> None:
        self._client = client
        self.limiter = AsyncLimiter(rate_per_minute, time_period=60)
        self._token = get_settings().github_token

    def supports_project(self, project: Project) -> bool:
        if project.symbol not in SYMBOL_TO_REPO:
            return False
        # Sin token, free tier (60 req/h) NO alcanza para 20+ repos.
        # Saltamos en lugar de quemarlo y triggering 403 rate-limit.
        return self._token is not None

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    @retry(**DEFAULT_RETRY_KWARGS, before_sleep=honor_retry_after)
    async def _fetch_commits_since(self, repo: str, since_iso: str) -> int:
        """Cuenta commits desde `since_iso`. Usa per_page=1 + Link header para count rápido.

        Pattern GitHub estándar: pedimos 1 página de 1 commit y leemos el último
        page number del Link header. Evita paginar 30 commits a la vez.
        """
        async with self.limiter:
            resp = await self._client.get(
                f"{GITHUB_BASE}/repos/{repo}/commits",
                params={"since": since_iso, "per_page": 1},
                headers=self._headers(),
            )
            resp.raise_for_status()
            link = resp.headers.get("Link", "")
            if 'rel="last"' in link:
                # Extract last page number — robust parsing of the Link header.
                for part in link.split(","):
                    if 'rel="last"' in part:
                        # part is like '<...&page=42>; rel="last"'
                        url = part.split(";")[0].strip().lstrip("<").rstrip(">")
                        # page param tail
                        page = url.split("page=")[-1]
                        try:
                            return int(page)
                        except ValueError:
                            return -1
            # No Link header → 0 or 1 commits
            return len(resp.json())

    @retry(**DEFAULT_RETRY_KWARGS, before_sleep=honor_retry_after)
    async def _fetch_contributors(self, repo: str) -> int:
        """Approx contributors activos. /contributors retorna lista (per_page default 30)."""
        async with self.limiter:
            resp = await self._client.get(
                f"{GITHUB_BASE}/repos/{repo}/contributors",
                params={"per_page": 100, "anon": "false"},
                headers=self._headers(),
            )
            if resp.status_code == 204:  # empty
                return 0
            resp.raise_for_status()
            return len(resp.json())

    async def fetch(self, project: Project, *, target_date: date) -> SourceSnapshot:
        assert project.id is not None
        repo = SYMBOL_TO_REPO[project.symbol]
        now_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)
        since_30 = (now_dt - timedelta(days=30)).isoformat()
        since_90 = (now_dt - timedelta(days=90)).isoformat()

        try:
            commits_30 = await self._fetch_commits_since(repo, since_30)
            commits_90 = await self._fetch_commits_since(repo, since_90)
            contributors = await self._fetch_contributors(repo)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ConnectorError(self.source, project.symbol, f"repo {repo} not found") from e
            raise ConnectorError(
                self.source,
                project.symbol,
                f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            ) from e
        except httpx.HTTPError as e:
            raise ConnectorError(self.source, project.symbol, f"Network: {e}") from e

        payload: dict[str, Any] = {
            "repo": repo,
            "commits_30d": commits_30,
            "commits_90d": commits_90,
            "contributors_top": contributors,
        }
        log.info(
            "github_fetch_ok",
            project=project.symbol,
            repo=repo,
            commits_30d=commits_30,
            commits_90d=commits_90,
        )
        return SourceSnapshot(
            project_id=project.id,
            source=self.source,
            snapshot_date=target_date,
            payload=payload,
        )
