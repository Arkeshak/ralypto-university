"""Deprecated: the evaluation harness moved to `procure.benchmark` (run `python project/main.py benchmark`).

Kept only so older imports keep working.
"""
from __future__ import annotations

from .benchmark import bootstrap_ci, forecast_eval, po_accurate, query_eval, reference_order, scale_eval  # noqa: F401
