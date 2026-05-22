"""SQLite connection helpers.

CRÍTICO: PRAGMA foreign_keys=ON debe activarse en CADA conexión (default OFF
en SQLite). El connection wrapper aquí lo aplica junto con el resto de PRAGMAs
de WAL/concurrency. El mismo patrón se usa desde Streamlit vía SQLAlchemy
event listener (ver streamlit_app.py).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import get_settings

# SQLite mínimo recomendado en R6: 3.35 (DROP COLUMN, generated columns).
MIN_SQLITE_VERSION = (3, 35, 0)


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Aplica PRAGMAs en orden. WAL primero, foreign_keys siempre, busy_timeout para concurrency."""
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA wal_autocheckpoint=1000")
    cur.close()


def check_sqlite_version() -> tuple[int, int, int]:
    """Verifica versión SQLite ≥ 3.35. Falla rápido si no."""
    version_str = sqlite3.sqlite_version
    parts = tuple(int(p) for p in version_str.split("."))
    if len(parts) != 3:
        raise RuntimeError(f"Unexpected SQLite version format: {version_str}")
    if parts < MIN_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite {'.'.join(str(p) for p in MIN_SQLITE_VERSION)}+ required; got {version_str}"
        )
    return parts  # type: ignore[return-value]


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Abre conexión SQLite con todos los PRAGMAs aplicados.

    El caller es responsable de cerrar la conexión. Para uso típico,
    preferir el context manager `connection()` que asegura cleanup.
    """
    if db_path is None:
        db_path = get_settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        isolation_level=None,  # autocommit; transacciones explícitas via BEGIN/COMMIT
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


@contextmanager
def connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager que asegura cierre de conexión."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transacción explícita per-project (ver pipeline/batch.py).

    Garantiza que crash a mitad deja N proyectos consistentes y M no
    actualizados, nunca un proyecto en estado intermedio.
    """
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def apply_migrations(db_path: Path | None = None, migrations_dir: Path | None = None) -> int:
    """Aplica migraciones yoyo pendientes. Retorna cantidad aplicada.

    Pattern programático recomendado por R6: usa lock para evitar runs paralelos.
    """
    from yoyo import get_backend, read_migrations

    settings = get_settings()
    db_path = db_path or settings.db_path
    migrations_dir = migrations_dir or settings.migrations_dir
    db_path.parent.mkdir(parents=True, exist_ok=True)

    check_sqlite_version()

    backend = get_backend(f"sqlite:///{db_path.as_posix()}")
    migrations = read_migrations(str(migrations_dir))
    with backend.lock():
        to_apply = backend.to_apply(migrations)
        applied = list(to_apply)
        backend.apply_migrations(to_apply)
    return len(applied)


def backup(db_path: Path | None = None, backups_dir: Path | None = None) -> Path:
    """Copia data/crypto.db a data/backups/crypto-YYYYMMDDHHMM.db.

    Usar antes de aplicar migraciones (R6: política forward-only sin rollback útil
    en single-dev; el backup es la red de seguridad real).
    """
    from datetime import datetime
    from shutil import copy2

    settings = get_settings()
    db_path = db_path or settings.db_path
    backups_dir = backups_dir or settings.backups_dir
    backups_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise FileNotFoundError(f"DB no existe en {db_path}; nada que respaldar.")

    stamp = datetime.utcnow().strftime("%Y%m%d%H%M")
    target = backups_dir / f"crypto-{stamp}.db"
    copy2(db_path, target)
    return target
