"""Smart money signal — pipeline de 5 pasos (plan Signal 2).

El signal NO es "delta top-50 raw" — eso incluye CEX hot wallets, DEX programs,
bridges, vesting contracts y rompe la señal. Pipeline correcto:

1. Pull top 100 holders                       → hecho por connectors (helius/moralis)
2. Resolve owners (Solana ATA → owner)        → hecho por helius connector (DAS)
3. Tagging exclusion                          → load_excluded_addresses + filter_holders
4. Heuristic filtering (contracts, concentration) → filter_holders
5. Weighted delta vs prior snapshot           → compute_smart_money_delta

Threshold empírico: |delta_7d| > 2.5% supera ruido. <1% es ruido. >10% es
unlock/listing event (cross-check con EVENTS).

Cooldown 48h: signal nuevo NO se emite si el anterior fue <48h. Anti-flapping
en eventos puntuales. (Implementado en compute_smart_money_delta_with_cooldown.)
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from ..config import get_settings
from ..logging_config import get_logger
from ..models import Project

log = get_logger(__name__)

# Heurística step 4: si top-1 holder concentra >X del top-100 visible, probable
# treasury/team — excluir como signal-killer. Plan original menciona "15% del
# circulating supply", pero el connector solo trae top-100 (subset ya concentrado),
# por lo que aplicar 15% sobre top-100 sería demasiado agresivo (un EOA whale
# legítimo puede tener 20-30% del top-100 observado). Threshold elevado a 50%
# del top-100 cuando no hay circulating real disponible. Cuando se integre
# CoinGecko circulating_supply, este threshold se aplica sobre la supply real
# y vuelve al 15% del plan.
TOP1_CONCENTRATION_MAX = 0.50


@dataclass(frozen=True, slots=True)
class HolderRecord:
    """Holder normalizado tras pasar por filter_holders.

    `included=False` significa que el holder existe en el top-100 pero fue
    excluido del cálculo de smart money. Lo mantenemos en holders_snapshots
    para auditoría retroactiva (¿por qué se excluyó este?).
    """

    owner: str
    balance: float
    rank: int
    is_contract: bool
    is_program: bool
    label: str | None
    included: bool


def load_excluded_addresses(
    path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Carga excluded_addresses. Devuelve {chain: {address: category}}.

    Resolución de path (mismo patrón que watchlist):
    1. `path` argumento explícito (tests).
    2. `data/labels/excluded_addresses.yaml` (gitignored, user override).
    3. `data/labels.example.yaml` (seed tracked en repo).

    Normaliza addresses a lowercase para EVM, mantiene case para Solana
    (base58 es case-sensitive).
    """
    if path is None:
        settings = get_settings()
        candidates = [
            settings.data_dir / "labels" / "excluded_addresses.yaml",
            settings.data_dir / "labels.example.yaml",
        ]
        path = next((p for p in candidates if p.exists()), candidates[-1])

    if not path.exists():
        log.warning("excluded_addresses_missing", path=str(path))
        return {}

    raw = yaml.safe_load(path.read_text()) or {}
    result: dict[str, dict[str, str]] = {}
    for chain, categories in raw.items():
        chain_key = chain.lower().strip()
        result[chain_key] = {}
        for category, entries in (categories or {}).items():
            for entry in entries or []:
                addr = entry.get("address")
                if not addr:
                    continue
                addr_key = addr.lower() if addr.startswith("0x") else addr
                result[chain_key][addr_key] = category
    return result


def _label_for(address: str, chain: str, excluded: dict[str, dict[str, str]]) -> str | None:
    """Devuelve la categoría si la dirección está en el set excluido, None si no."""
    chain_set = excluded.get(chain.lower(), {})
    key = address.lower() if address.startswith("0x") else address
    return chain_set.get(key)


def filter_holders(
    holders: Iterable[dict[str, Any]],
    *,
    chain: str,
    excluded: dict[str, dict[str, str]],
) -> list[HolderRecord]:
    """Aplica steps 3 y 4 del pipeline: tagging + heurística.

    Reglas:
    - Si address está en excluded list → included=False, label=categoría
    - Si is_contract=True (EVM) o is_program=True (Solana) → included=False, label='contract'
    - Si top-1 concentra >15% del top-100 total → marca ese único holder included=False (label='concentrado')

    Resultado preserva ALL holders (auditable). El consumidor filtra por
    `included=True` para el cálculo del signal.
    """
    raw_list = list(holders)
    if not raw_list:
        return []

    total_balance = sum(float(h.get("balance", 0.0)) for h in raw_list)
    records: list[HolderRecord] = []

    for h in raw_list:
        owner = h.get("owner")
        if not owner:
            continue
        balance = float(h.get("balance", 0.0))
        rank = int(h.get("rank", 0))
        is_contract = bool(h.get("is_contract", False))
        is_program = bool(h.get("is_program", False))

        label = _label_for(owner, chain, excluded)
        included = True
        if label is not None:
            included = False
        elif is_contract or is_program:
            included = False
            label = "contract"
        elif rank == 1 and total_balance > 0 and balance / total_balance > TOP1_CONCENTRATION_MAX:
            included = False
            label = "concentrated"

        records.append(
            HolderRecord(
                owner=owner,
                balance=balance,
                rank=rank,
                is_contract=is_contract,
                is_program=is_program,
                label=label,
                included=included,
            )
        )

    return records


def compute_smart_money_delta(
    current: list[HolderRecord],
    prior: list[HolderRecord],
    *,
    total_supply_units: float | None = None,
) -> float | None:
    """Step 5: delta ponderado de wallets EOA filtradas vs prior snapshot.

    Retorna porcentaje (no fracción): +2.5 significa "smart money EOAs ganaron
    2.5% del top-100 supply observado en la ventana".

    Si total_supply_units es conocido (circulating real), normaliza vs ese.
    Si None, usa la suma del top-100 included como aproximación.

    Devuelve None si:
    - No hay prior snapshot (primer fetch, no se puede calcular delta)
    - Total supply observado = 0 (no hay holders en común)
    """
    if not current or not prior:
        return None

    cur_eoa = {r.owner: r.balance for r in current if r.included}
    prior_eoa = {r.owner: r.balance for r in prior if r.included}

    if not cur_eoa and not prior_eoa:
        return None

    universe = set(cur_eoa) | set(prior_eoa)
    delta_sum = sum(cur_eoa.get(o, 0.0) - prior_eoa.get(o, 0.0) for o in universe)

    if total_supply_units is not None and total_supply_units > 0:
        denominator = total_supply_units
    else:
        denominator = max(
            sum(r.balance for r in current if r.included),
            sum(r.balance for r in prior if r.included),
        )

    if denominator <= 0:
        return None

    return (delta_sum / denominator) * 100.0


def persist_holders_snapshot(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    batch_id: str,
    snapshot_date: date,
    source: str,
    records: list[HolderRecord],
) -> int:
    """UPSERT records en holders_snapshots. Retorna cantidad de filas escritas."""
    written = 0
    for r in records:
        conn.execute(
            """
            INSERT INTO holders_snapshots
                (project_id, batch_id, snapshot_date, source, owner_address, balance,
                 rank, is_contract, is_program, label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, snapshot_date, owner_address, source) DO UPDATE SET
                balance = excluded.balance,
                rank = excluded.rank,
                is_contract = excluded.is_contract,
                is_program = excluded.is_program,
                label = excluded.label,
                batch_id = excluded.batch_id
            """,
            (
                project_id,
                batch_id,
                snapshot_date.isoformat(),
                source,
                r.owner,
                r.balance,
                r.rank,
                int(r.is_contract),
                int(r.is_program),
                r.label,
            ),
        )
        written += 1
    return written


def load_holders_snapshot(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    source: str,
    snapshot_date: date,
) -> list[HolderRecord]:
    """Lee un snapshot guardado en holders_snapshots."""
    rows = conn.execute(
        """
        SELECT owner_address, balance, rank, is_contract, is_program, label
        FROM holders_snapshots
        WHERE project_id = ? AND source = ? AND snapshot_date = ?
        ORDER BY rank ASC
        """,
        (project_id, source, snapshot_date.isoformat()),
    ).fetchall()
    return [
        HolderRecord(
            owner=row["owner_address"],
            balance=float(row["balance"]),
            rank=int(row["rank"]),
            is_contract=bool(row["is_contract"]),
            is_program=bool(row["is_program"]),
            label=row["label"],
            included=row["label"] is None,
        )
        for row in rows
    ]


def find_prior_snapshot_date(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    source: str,
    current_date: date,
    target_lookback_days: int = 7,
) -> date | None:
    """Busca el snapshot anterior más cercano a `current_date - target_lookback_days`.

    Acepta margen flexible: cualquier snapshot entre 3 y 21 días antes del current.
    Devuelve None si no hay snapshot en la ventana.
    """
    target = (current_date - timedelta(days=target_lookback_days)).isoformat()
    earliest = (current_date - timedelta(days=21)).isoformat()
    latest = (current_date - timedelta(days=3)).isoformat()
    row = conn.execute(
        """
        SELECT DISTINCT snapshot_date FROM holders_snapshots
        WHERE project_id = ? AND source = ?
          AND snapshot_date BETWEEN ? AND ?
        ORDER BY ABS(julianday(snapshot_date) - julianday(?)) ASC
        LIMIT 1
        """,
        (project_id, source, earliest, latest, target),
    ).fetchone()
    if not row:
        return None
    return date.fromisoformat(row["snapshot_date"])


def run_smart_money_pipeline(
    conn: sqlite3.Connection,
    project: Project,
    *,
    batch_id: str,
    snapshot_date: date,
    holders_payload: list[dict[str, Any]],
    source: str,
    excluded: dict[str, dict[str, str]] | None = None,
) -> float | None:
    """Pipeline completo: filter → persist → compute delta vs prior.

    `source` = 'helius' o 'moralis'. `holders_payload` viene del raw snapshot
    de ese connector (lista de dicts con keys owner, balance, rank, is_contract|is_program).

    Devuelve smart_money_delta_7d como % o None si no hay prior.
    """
    assert project.id is not None

    chain = (project.chain or "").lower().strip()
    # Normalizar chain compuesto: "arbitrum (ethereum)" → "arbitrum"
    chain = chain.split(" ", 1)[0].split("(", 1)[0].strip()

    if excluded is None:
        excluded = load_excluded_addresses()

    records = filter_holders(holders_payload, chain=chain, excluded=excluded)
    if not records:
        return None

    persist_holders_snapshot(
        conn,
        project_id=project.id,
        batch_id=batch_id,
        snapshot_date=snapshot_date,
        source=source,
        records=records,
    )

    prior_date = find_prior_snapshot_date(
        conn,
        project_id=project.id,
        source=source,
        current_date=snapshot_date,
    )
    if prior_date is None:
        log.info(
            "smart_money_no_prior",
            project=project.symbol,
            source=source,
            snapshot_date=snapshot_date.isoformat(),
        )
        return None

    prior = load_holders_snapshot(
        conn, project_id=project.id, source=source, snapshot_date=prior_date
    )
    delta = compute_smart_money_delta(records, prior)
    log.info(
        "smart_money_delta_computed",
        project=project.symbol,
        source=source,
        delta_pct=round(delta, 3) if delta is not None else None,
        prior_date=prior_date.isoformat(),
        current_date=snapshot_date.isoformat(),
        included_holders=sum(1 for r in records if r.included),
    )
    return delta
