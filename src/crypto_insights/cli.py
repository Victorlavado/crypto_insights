"""CLI entry point: `crypto-insights <command> [--json]`.

Cumple el agent-native contract: cada subcomando expone --json para que un
agente pueda consumirlo. Discovery via `crypto-insights tools`.

Subcomandos disponibles en Fase 0:
    init-db                     aplica migraciones yoyo
    backup                      copia DB a data/backups/
    sync-watchlist              UPSERT watchlist a tabla projects
    list                        lista proyectos cargados
    batch-daily --date          ejecuta batch para fecha (idempotente)
    batch-status [--id|--latest] estado de un batch
    state SYMBOL                estado actual de un proyecto
    tools                       capability discovery

Más subcomandos llegan con cada fase (Fase 1: viability; Fase 2: signal-history;
Fase 3: events, etc).
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated

import typer

from . import db as db_mod
from .config import get_settings
from .logging_config import configure_logging
from .watchlist import list_projects, sync_watchlist

app = typer.Typer(
    name="crypto-insights",
    help="Crypto position manager: pipeline batch + dashboard local.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)


def _print(payload: dict | list, *, as_json: bool) -> None:
    """Imprime estructurado (JSON) o human-readable (rich/text)."""
    if as_json:
        sys.stdout.write(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
        sys.stdout.write("\n")
        return
    # Human fallback — JSON pretty without ensure_ascii.
    sys.stdout.write(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
    sys.stdout.write("\n")


@app.command(name="init-db")
def init_db(
    *,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Aplica migraciones yoyo. Crea data/crypto.db si no existe."""
    settings = get_settings()
    settings.ensure_dirs()
    applied = db_mod.apply_migrations()
    _print(
        {
            "action": "init-db",
            "db_path": str(settings.db_path),
            "migrations_applied": applied,
        },
        as_json=json_out,
    )


@app.command()
def backup(
    *,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Copia data/crypto.db a data/backups/crypto-YYYYMMDDHHMM.db."""
    target = db_mod.backup()
    _print({"action": "backup", "target": str(target)}, as_json=json_out)


@app.command(name="sync-watchlist")
def cmd_sync_watchlist(
    *,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """UPSERT watchlist YAML a la tabla projects (idempotente)."""
    with db_mod.connection() as conn:
        projects = sync_watchlist(conn)
    _print(
        {
            "action": "sync-watchlist",
            "count": len(projects),
            "projects": [
                {"id": p.id, "symbol": p.symbol, "archetype": p.archetype.value} for p in projects
            ],
        },
        as_json=json_out,
    )


@app.command(name="list")
def cmd_list(
    archetype: Annotated[
        str | None, typer.Option("--archetype", help="Filter by archetype")
    ] = None,
    *,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Lista proyectos cargados en la DB. --archetype filtra."""
    with db_mod.connection() as conn:
        projects = list_projects(conn)
    if archetype:
        projects = [p for p in projects if p.archetype.value == archetype]
    _print(
        [
            {
                "symbol": p.symbol,
                "archetype": p.archetype.value,
                "chain": p.chain,
                "coingecko_id": p.coingecko_id,
            }
            for p in projects
        ],
        as_json=json_out,
    )


@app.command(name="state")
def cmd_state(
    symbol: str,
    *,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Estado actual de un proyecto (PROJECT_STATE). Devuelve unknown si no hay batch aún."""
    with db_mod.connection() as conn:
        row = conn.execute(
            """
            SELECT p.symbol, p.archetype, ps.current_state, ps.composite_score,
                   ps.reason_code, ps.reason_data, ps.reason_human, ps.layer2_flag,
                   ps.has_gaps, ps.batches_in_state, ps.batch_id, ps.updated_at
            FROM projects p
            LEFT JOIN project_state ps ON ps.project_id = p.id
            WHERE p.symbol = ?
            """,
            (symbol,),
        ).fetchone()
    if not row:
        typer.echo(f"Unknown symbol: {symbol!r}", err=True)
        raise typer.Exit(2)
    out = {
        "symbol": row["symbol"],
        "archetype": row["archetype"],
        "current_state": row["current_state"] or "unknown",
        "composite_score": row["composite_score"],
        "reason_code": row["reason_code"] or "NORMAL",
        "reason_data": json.loads(row["reason_data"]) if row["reason_data"] else None,
        "reason_human": row["reason_human"],
        "layer2_flag": row["layer2_flag"],
        "has_gaps": bool(row["has_gaps"]) if row["has_gaps"] is not None else None,
        "batches_in_state": row["batches_in_state"],
        "batch_id": row["batch_id"],
        "updated_at": row["updated_at"],
    }
    _print(out, as_json=json_out)


@app.command(name="batch-status")
def cmd_batch_status(
    latest: Annotated[bool, typer.Option("--latest", help="Show latest batch")] = False,
    batch_id: Annotated[
        str | None, typer.Option("--id", help="Specific batch id (YYYY-MM-DD)")
    ] = None,
    *,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Estado de un batch. --latest o --id YYYY-MM-DD."""
    if not latest and not batch_id:
        typer.echo("Provide --latest or --id YYYY-MM-DD", err=True)
        raise typer.Exit(2)
    with db_mod.connection() as conn:
        if latest:
            row = conn.execute("SELECT * FROM batches ORDER BY started_at DESC LIMIT 1").fetchone()
        else:
            row = conn.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    if not row:
        _print({"batch_id": batch_id, "status": "not_found"}, as_json=json_out)
        return
    out = {
        "batch_id": row["batch_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "heartbeat_at": row["heartbeat_at"],
        "finished_at": row["finished_at"],
        "error_summary": json.loads(row["error_summary"]) if row["error_summary"] else None,
    }
    _print(out, as_json=json_out)


@app.command(name="batch-daily")
def cmd_batch_daily(
    target_date: Annotated[
        str | None, typer.Option("--date", help="Batch date (YYYY-MM-DD). Defaults to today UTC")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Plan without writes")] = False,
    *,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Ejecuta el batch diario. Idempotente por date."""
    from datetime import date as _date

    from .pipeline.batch import run_batch

    target = _date.fromisoformat(target_date) if target_date else _date.today()
    result = asyncio.run(run_batch(target, dry_run=dry_run))
    _print(
        {
            "batch_id": result.batch_id,
            "status": result.status.value,
            "sources_ok": result.sources_ok,
            "sources_failed": [
                {
                    "source": f.source,
                    "project": f.project_symbol,
                    "error": f.error,
                }
                for f in result.sources_failed
            ],
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
            "dry_run": dry_run,
        },
        as_json=json_out,
    )


@app.command()
def tools(
    *,
    json_out: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Capability discovery — lista subcomandos disponibles (MCP-style).

    Cumple el agent-native contract: agentes consumen este endpoint para
    descubrir qué pueden hacer sin abrir el dashboard.
    """
    cmds = []
    for cmd in app.registered_commands:
        if cmd.callback is None:
            continue
        cmds.append(
            {
                "name": cmd.name or cmd.callback.__name__.replace("_", "-"),
                "help": cmd.help or (cmd.callback.__doc__ or "").splitlines()[0].strip()
                if cmd.callback.__doc__
                else "",
            }
        )
    _print(
        {"version": "0.1.0", "commands": sorted(cmds, key=lambda c: c["name"])}, as_json=json_out
    )


def main() -> None:
    """Entry point invocado por `crypto-insights` (registrado en pyproject)."""
    configure_logging()
    app()


def ui() -> None:
    """Entry point invocado por `crypto-ui` — lanza Streamlit."""
    import sys

    from streamlit.web import cli as stcli

    settings = get_settings()
    streamlit_app = settings.project_root / "streamlit_app.py"
    sys.argv = ["streamlit", "run", str(streamlit_app)]
    stcli.main()


if __name__ == "__main__":
    main()
