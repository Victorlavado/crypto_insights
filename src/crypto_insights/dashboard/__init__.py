"""Dashboard helpers — separados de streamlit_app.py para reuso desde CLI/tests.

Agent-native parity: streamlit_app.py NO debe tener SQL inline. Toda lectura
va a través de `dashboard.api` que es lo que CLI también expone.
"""

from .api import (
    get_all_states,
    get_batch_status,
    get_derived_signals_history,
    get_project_detail,
)

__all__ = [
    "get_all_states",
    "get_batch_status",
    "get_derived_signals_history",
    "get_project_detail",
]
