"""Pipeline batch + persistencia + derivadas.

Orquesta el batch diario:
    1. Cleanup huérfanos (status=running > 2h sin heartbeat → failed)
    2. Register batch started
    3. Fan-out connectors con TaskGroup (R1)
    4. UPSERT raw_snapshots con COALESCE (no sobrescribir con NULL)
    5. Per-project transacción: derived_signals + project_state + history
    6. Register batch finished con error_summary estructurado
"""

from .batch import run_batch
from .persist import (
    cleanup_orphan_batches,
    finalize_batch,
    register_batch_started,
    update_heartbeat,
    upsert_raw_snapshot,
)

__all__ = [
    "cleanup_orphan_batches",
    "finalize_batch",
    "register_batch_started",
    "run_batch",
    "update_heartbeat",
    "upsert_raw_snapshot",
]
