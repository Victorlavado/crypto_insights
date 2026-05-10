"""Connectors aislados por fuente externa.

Cada connector implementa el Connector Protocol (ver base.py):
    - source: ClassVar[str]
    - supports_project(p: Project) -> bool
    - async fetch(p: Project, *, date: date) -> SourceSnapshot

Encapsulan rate limiting (aiolimiter) y retry (tenacity) por host. Una falla
aislada no tira el batch (ver pipeline/batch.py).
"""

from .base import Connector, ConnectorError, build_http_client
from .binance import BinanceConnector

__all__ = ["BinanceConnector", "Connector", "ConnectorError", "build_http_client"]
