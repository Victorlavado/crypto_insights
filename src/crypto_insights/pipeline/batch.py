"""Orquestador del batch diario.

Patrón TaskGroup (Python 3.12+, R1): captura excepciones por task sin silenciar
KeyboardInterrupt/CancelledError. Heartbeat en background task. Transacción
per-project para que crash a mitad deje N proyectos consistentes y M no
actualizados, nunca uno en estado intermedio (R-crítico #8).

Fase 0: solo Binance, sin derived/state computation (eso es Fase 1+).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Protocol

import httpx

from .. import db as db_mod
from ..connectors import (
    BinanceConnector,
    DeFiLlamaConnector,
    GitHubConnector,
    HeliusConnector,
    HyperliquidConnector,
    MoralisConnector,
)
from ..connectors.base import ConnectorError, build_http_client
from ..logging_config import get_logger
from ..models import BatchResult, BatchStatus, ConnectorFailure, ConnectorResult, Project
from ..watchlist import list_projects, sync_watchlist
from .persist import (
    cleanup_orphan_batches,
    finalize_batch,
    register_batch_started,
    update_heartbeat,
    upsert_raw_snapshot,
)

log = get_logger(__name__)


class _ConnectorLike(Protocol):
    """Minimal Protocol — duck-typed; cada connector concreto lo implementa por construcción."""

    source: str

    def supports_project(self, project: Project) -> bool: ...
    async def fetch(self, project: Project, *, target_date: date) -> object: ...


async def _safe_fetch(
    connector: _ConnectorLike, project: Project, target_date: date
) -> ConnectorResult:
    """Wrapper que devuelve ConnectorResult en lugar de propagar excepción.

    No usamos `gather(return_exceptions=True)` porque silencia
    KeyboardInterrupt/CancelledError (R1). En su lugar wrapping explícito.
    """
    try:
        snap = await connector.fetch(project, target_date=target_date)
        return ConnectorResult.ok(snap)  # type: ignore[arg-type]
    except ConnectorError as e:
        log.warning(
            "connector_failed", source=connector.source, project=project.symbol, error=str(e)
        )
        return ConnectorResult.failed(connector.source, project.symbol, str(e))
    except Exception as e:
        # Catch-all defensivo: cualquier excepción no prevista se trata como failure aislada,
        # NO tira el batch. Loggeamos con traceback implícito a través de structlog.
        log.exception(
            "connector_exception", source=connector.source, project=project.symbol, error=str(e)
        )
        return ConnectorResult.failed(connector.source, project.symbol, f"{type(e).__name__}: {e}")


async def _heartbeat_loop(batch_id: str, interval_seconds: int) -> None:
    """Actualiza heartbeat_at cada `interval_seconds` mientras el batch corre.

    Se cancela cuando el TaskGroup termina (CancelledError propaga limpio).
    """
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            with db_mod.connection() as hb_conn:
                update_heartbeat(hb_conn, batch_id)
    except asyncio.CancelledError:
        return


def _build_connectors(client: httpx.AsyncClient) -> Sequence[_ConnectorLike]:
    """Construye conectores con el client compartido.

    Fase 0: Binance. Fase 1: + DeFiLlama, GitHub. Fase 2: + Hyperliquid,
    Helius, Moralis. Helius/Moralis solo activos si la API key está
    configurada — sin ella, supports_project sigue True pero el fetch
    falla limpio con ConnectorError y queda como gap.
    """
    from ..config import get_settings

    settings = get_settings()
    return [
        BinanceConnector(client),
        DeFiLlamaConnector(client),
        GitHubConnector(client),
        HyperliquidConnector(client),
        HeliusConnector(client, settings.helius_api_key),
        MoralisConnector(client, settings.moralis_api_key),
    ]


async def run_batch(target_date: date, *, dry_run: bool = False) -> BatchResult:
    """Ejecuta el batch diario para `target_date`.

    Idempotente: re-ejecutarlo el mismo día sobrescribe (UPSERT con COALESCE),
    no duplica ni sobrescribe con NULLs. Tolerante a fallos parciales: una
    fuente caída deja gap, no tira el batch.

    `dry_run=True` planifica sin escribir nada — útil para preview de qué
    fetches saldrían y qué projects están en scope.
    """
    from ..config import get_settings

    settings = get_settings()
    settings.ensure_dirs()

    batch_id = target_date.isoformat()
    started_at = datetime.now(UTC)
    failures: list[ConnectorFailure] = []
    ok_count = 0

    log.info("batch_starting", batch_id=batch_id, dry_run=dry_run)

    if not dry_run:
        with db_mod.connection() as conn:
            n_orphans = cleanup_orphan_batches(
                conn, threshold_hours=settings.orphan_batch_threshold_hours
            )
            if n_orphans:
                log.warning("orphan_batches_cleaned", count=n_orphans)
            register_batch_started(conn, batch_id)

    # Asegurar que projects está sincronizado con watchlist (idempotente).
    # También sincronizamos events.yaml a la tabla EVENTS al inicio.
    with db_mod.connection() as conn:
        projects = sync_watchlist(conn) if not dry_run else list_projects(conn)
        if not dry_run:
            try:
                from ..connectors.events_manual import sync_events_to_db

                sync_events_to_db(conn)
            except FileNotFoundError:
                log.warning("events_yaml_missing", note="data/events.yaml not found; skipping")

    async with build_http_client() as client:
        connectors = _build_connectors(client)

        # Construir lista de (connector, project) válidos antes del fan-out.
        pairs: list[tuple[_ConnectorLike, Project]] = []
        for project in projects:
            for connector in connectors:
                if connector.supports_project(project):
                    pairs.append((connector, project))

        log.info("batch_planned", batch_id=batch_id, fetches=len(pairs), projects=len(projects))

        if dry_run:
            finished_at = datetime.now(UTC)
            return BatchResult(
                batch_id=batch_id,
                status=BatchStatus.COMPLETE,
                sources_ok=len(pairs),
                sources_failed=[],
                started_at=started_at,
                finished_at=finished_at,
            )

        # Fan-out: TaskGroup + heartbeat en background.
        async with asyncio.TaskGroup() as tg:
            hb_task = tg.create_task(_heartbeat_loop(batch_id, settings.heartbeat_interval_seconds))
            fetch_tasks = [tg.create_task(_safe_fetch(c, p, target_date)) for c, p in pairs]
            # Esperar a que terminen todos los fetches; luego cancelar heartbeat.
            for t in fetch_tasks:
                await t
            hb_task.cancel()

        results = [t.result() for t in fetch_tasks]

    # Persistir snapshots OK
    with db_mod.connection() as conn:
        for r in results:
            if r.is_ok and r.snapshot is not None:
                upsert_raw_snapshot(conn, r.snapshot, batch_id)
                ok_count += 1
            elif r.failure is not None:
                failures.append(r.failure)

    # Per-project transacción: derived signals + Layer 2 + Layer 1.
    # Garantiza que crash a mitad deja N proyectos consistentes y M no
    # actualizados, nunca uno en estado intermedio (R-crítico #8).
    from ..fusion.layer1 import evaluate_layer1, upsert_layer1_state
    from ..fusion.layer2 import evaluate_layer2, upsert_layer2_state
    from .derived import compute_derived_for_project, persist_derived_for_project

    with db_mod.connection() as conn:
        for project in projects:
            try:
                with db_mod.transaction(conn):
                    derived = compute_derived_for_project(conn, project, target_date)
                    persist_derived_for_project(conn, derived, batch_id)
                    layer2_result = evaluate_layer2(conn, project, target_date)

                    if layer2_result.blocked:
                        # Layer 2 override → blocked persiste directo, Layer 1 no corre
                        upsert_layer2_state(conn, layer2_result, batch_id)
                        log.info(
                            "layer2_blocked",
                            project=project.symbol,
                            reason_code=layer2_result.reason_code.value,
                            total_weighted=round(layer2_result.unlock_result.total_weighted, 2)
                            if layer2_result.unlock_result
                            else None,
                        )
                    else:
                        # Layer 1 corre: composite score + state
                        prior = conn.execute(
                            "SELECT current_state FROM project_state WHERE project_id = ?",
                            (project.id,),
                        ).fetchone()
                        from ..models import ProjectStateValue as _PSV

                        prior_state = _PSV(prior["current_state"]) if prior else None
                        layer1_result = evaluate_layer1(conn, project, prior_state=prior_state)
                        upsert_layer1_state(
                            conn, project, layer1_result, layer2_result.flag.value, batch_id
                        )
            except Exception as e:
                # Falla aislada por proyecto no tira el batch.
                log.exception("fusion_evaluation_failed", project=project.symbol, error=str(e))

    # Determinar status final
    if not failures:
        status = BatchStatus.COMPLETE
    elif ok_count > 0:
        status = BatchStatus.PARTIAL
    else:
        status = BatchStatus.FAILED

    with db_mod.connection() as conn:
        finalize_batch(conn, batch_id, status=status, failures=failures)

    finished_at = datetime.now(UTC)
    log.info(
        "batch_finished",
        batch_id=batch_id,
        status=status.value,
        sources_ok=ok_count,
        sources_failed=len(failures),
        duration_s=round((finished_at - started_at).total_seconds(), 1),
    )

    return BatchResult(
        batch_id=batch_id,
        status=status,
        sources_ok=ok_count,
        sources_failed=failures,
        started_at=started_at,
        finished_at=finished_at,
    )
