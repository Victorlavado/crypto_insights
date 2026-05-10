"""Streamlit dashboard — entry point.

Pull-only sobre SQLite WAL. Cualquier widget consume `dashboard.api` (no SQL
inline) para mantener agent-native parity.

Cache TTL 1h con `batch_id` como invalidador (al detectar nuevo batch_id,
miss automático).
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Permite ejecutar como `streamlit run streamlit_app.py` sin instalar el package.
sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st
from sqlalchemy import event
from sqlalchemy.engine import Engine

from crypto_insights.config import get_settings
from crypto_insights.dashboard.api import (
    create_feedback_entry,
    get_all_states,
    get_batch_status,
    get_project_detail,
)
from crypto_insights.db import connection


# ── Configuración SQLite (PRAGMAs en cada conexión) ───────────────────
@event.listens_for(Engine, "connect")
def _sqlite_pragma(dbapi_conn: object, _: object) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA wal_autocheckpoint=1000")
    cur.close()


st.set_page_config(
    page_title="Crypto Position Manager",
    page_icon="📊",
    layout="wide",
)


# ── Cached queries (TTL 1h, invalidador via batch_id) ─────────────────
@st.cache_data(ttl="1h")
def _cached_all_states(batch_id: str | None) -> list[dict]:  # noqa: ARG001
    """batch_id en signature para invalidar cache al ver nuevo batch."""
    with connection() as conn:
        return get_all_states(conn)


@st.cache_data(ttl="5m")
def _cached_batch_status() -> dict | None:
    with connection() as conn:
        return get_batch_status(conn)


def _cached_project_detail(symbol: str, batch_id: str | None) -> dict | None:  # noqa: ARG001
    """No cacheamos detail — es raro que el user haga drill-down rápido."""
    with connection() as conn:
        return get_project_detail(conn, symbol)


# ── Helpers de render ──────────────────────────────────────────────────
STATE_COLORS = {
    "aceleracion": "🟢",
    "acumulacion": "🟦",
    "distribucion": "🟠",
    "colapso": "🔴",
    "reset": "⚪",
    "blocked": "🚫",
    "degraded": "⚠️",
    "unknown": "❓",
}

FLAG_COLORS = {
    "green": "🟢",
    "amber": "🟡",
    "red": "🔴",
}


def _format_score(score: float | None) -> str:
    if score is None:
        return "—"
    sign = "+" if score >= 0 else ""
    return f"{sign}{score:.2f}"


def _format_last_updated(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        delta = datetime.utcnow() - dt.replace(tzinfo=None)
        seconds = delta.total_seconds()
        if seconds < 3600:
            return f"hace {int(seconds / 60)}m"
        if seconds < 86400:
            return f"hace {int(seconds / 3600)}h"
        return f"hace {int(seconds / 86400)}d"
    except (ValueError, TypeError):
        return iso_str


# ── Header ─────────────────────────────────────────────────────────────
st.title("Crypto Position Manager")

batch = _cached_batch_status()
batch_id = batch["batch_id"] if batch else None

if batch:
    cols = st.columns([2, 1, 1])
    cols[0].caption(f"Batch ref: **{batch['batch_id']}** ({batch['status']})")
    cols[1].caption(f"Última actualización: **{_format_last_updated(batch['finished_at'])}**")
    err_count = (
        len(batch.get("error_summary", {}).get("sources_failed", []))
        if batch.get("error_summary")
        else 0
    )
    cols[2].caption(f"Sources con error: **{err_count}**" if err_count else "Sources OK")
else:
    st.warning(
        "No hay batches todavía. Corre `uv run crypto-insights batch-daily` desde la terminal."
    )
    st.stop()

# ── Carga datos ─────────────────────────────────────────────────────────
states = _cached_all_states(batch_id)

# Resumen
summary_cols = st.columns(8)
state_counts = Counter(s["current_state"] for s in states)
for i, (state_name, emoji) in enumerate(STATE_COLORS.items()):
    summary_cols[i].metric(
        label=f"{emoji} {state_name}",
        value=state_counts.get(state_name, 0),
    )

st.divider()

# ── Tabs por archetype + blocked ────────────────────────────────────────
by_archetype: dict[str, list[dict]] = defaultdict(list)
blocked: list[dict] = []
for s in states:
    if s["current_state"] == "blocked":
        blocked.append(s)
    else:
        by_archetype[s["archetype"]].append(s)

# También añadir blocked a su archetype para context
for s in blocked:
    by_archetype[s["archetype"]].append(s)

archetype_order = [
    "infra-pmf",
    "tesis-macro",
    "l1-maduro",
    "defi-blue-chip",
    "memecoin-brand",
    "post-tge",
]

tab_labels = [f"{a} ({len(by_archetype.get(a, []))})" for a in archetype_order] + [
    f"blocked ({len(blocked)})"
]

tabs = st.tabs(tab_labels)

for i, archetype in enumerate(archetype_order):
    with tabs[i]:
        items = by_archetype.get(archetype, [])
        if not items:
            st.info(f"No hay proyectos en archetype {archetype}.")
            continue
        st.dataframe(
            [
                {
                    "Symbol": s["symbol"],
                    "State": f"{STATE_COLORS.get(s['current_state'], '?')} {s['current_state']}",
                    "Flag L2": f"{FLAG_COLORS.get(s['layer2_flag'], '?')} {s['layer2_flag']}",
                    "Score": _format_score(s["composite_score"]),
                    "Gaps": "⚠️" if s["has_gaps"] else "",
                    "Batches": s["batches_in_state"] or "—",
                    "Razón": s["reason_human"] or "—",
                }
                for s in items
            ],
            hide_index=True,
            use_container_width=True,
        )

with tabs[-1]:
    if not blocked:
        st.success("No hay proyectos blocked.")
    else:
        for s in blocked:
            st.subheader(f"🚫 {s['symbol']}  ({s['archetype']})")
            st.write(f"**Razón**: {s['reason_human']}")
            if s["reason_data"]:
                with st.expander("Reason data"):
                    st.json(s["reason_data"])
            st.caption(f"Estado activo durante {s['batches_in_state']} batches consecutivos")
            st.divider()

# ── Drill-down ──────────────────────────────────────────────────────────
st.divider()
st.subheader("Drill-down")
symbol_to_inspect = st.selectbox(
    "Seleccionar proyecto",
    options=[s["symbol"] for s in states],
    index=0,
)
if symbol_to_inspect:
    detail = _cached_project_detail(symbol_to_inspect, batch_id)
    if detail is None:
        st.error(f"Sin datos para {symbol_to_inspect}")
    else:
        col1, col2 = st.columns([2, 1])

        with col1:
            st.markdown(f"### {detail['symbol']} ({detail['archetype']})")
            st.write(
                f"**State**: {STATE_COLORS.get(detail['current_state'], '?')} `{detail['current_state']}`"
            )
            st.write(
                f"**Flag**: {FLAG_COLORS.get(detail['layer2_flag'], '?')} `{detail['layer2_flag']}`"
            )
            st.write(f"**Composite**: `{_format_score(detail['composite_score'])}`")
            st.write(f"**Reason**: {detail['reason_human'] or 'sin razón explícita'}")
            if detail["notes"]:
                st.caption(detail["notes"])

            if detail["layer1_scores"]:
                st.markdown("**Layer 1 scores (signal contributions)**")
                st.dataframe(
                    [
                        {
                            "Signal": name,
                            "Value": data.get("value"),
                            "Weight": data.get("weight"),
                            "Normalized": data.get("normalized"),
                            "Contribution": data.get("contribution"),
                        }
                        for name, data in detail["layer1_scores"].items()
                    ],
                    hide_index=True,
                )

        with col2:
            st.markdown("**Upcoming events (next 4-8w)**")
            if detail["upcoming_events"]:
                st.dataframe(detail["upcoming_events"], hide_index=True)
            else:
                st.info("Sin eventos próximos en la ventana.")

            st.markdown("**Último raw fetch por source**")
            seen_sources = set()
            recent = []
            for s in detail["raw_snapshots"]:
                if s["source"] not in seen_sources:
                    seen_sources.add(s["source"])
                    recent.append(s)
            st.dataframe(recent, hide_index=True)

# ── Crear feedback ──────────────────────────────────────────────────────
st.divider()
st.subheader("Crear entrada de feedback")
with st.form("feedback_form"):
    fb_symbols = st.multiselect(
        "Proyectos referenciados",
        options=[s["symbol"] for s in states],
        default=[symbol_to_inspect] if symbol_to_inspect else [],
    )
    fb_signals = st.text_input(
        "Signals referenciadas (separados por coma)",
        placeholder="consolidation_breakout, funding_zscore_30d",
    )
    fb_notes = st.text_area(
        "Observación",
        placeholder="Lo que observaste en este momento sobre estos proyectos / signals…",
        height=120,
    )
    submitted = st.form_submit_button("Crear archivo en docs/feedback/")
    if submitted:
        if not fb_symbols or not fb_notes.strip():
            st.error("Selecciona al menos 1 proyecto y escribe una nota.")
        else:
            signal_list = [s.strip() for s in fb_signals.split(",") if s.strip()] or None
            path = create_feedback_entry(
                get_settings().project_root,
                symbols=fb_symbols,
                notes=fb_notes,
                signals_referenced=signal_list,
            )
            st.success(f"Feedback creado en `{path}`")
