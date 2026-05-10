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
from .defillama import DeFiLlamaConnector
from .events_manual import EventsManualConnector
from .github import GitHubConnector
from .helius import HeliusConnector
from .hyperliquid import HyperliquidConnector
from .moralis import MoralisConnector

__all__ = [
    "BinanceConnector",
    "Connector",
    "ConnectorError",
    "DeFiLlamaConnector",
    "EventsManualConnector",
    "GitHubConnector",
    "HeliusConnector",
    "HyperliquidConnector",
    "MoralisConnector",
    "build_http_client",
]
