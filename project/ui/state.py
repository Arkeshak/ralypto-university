"""Shared UI state: the demo ERP database, the cached service and the acting user."""
from __future__ import annotations

import os

import streamlit as st

from procure.data import generate, schema_ok
from procure.llm import LLM, load_env
from procure.service import ProcureService

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, "data", "demo.db")
TRACE = os.path.join(ROOT, "results", "demo", "ui_trace.jsonl")
ROLE_USERS = {"viewer": "carol", "buyer": "alice", "approver": "bob", "admin": "root"}


def ensure_db(seed: int = 1, skus: int = 40, profile: str = "supermarket", force: bool = False):
    if force or not schema_ok(DB):  # regenerate when missing or created by an older schema
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        generate(DB, seed=seed, n_skus=skus, profile=profile)


@st.cache_resource(show_spinner=False)
def _service(version: int) -> ProcureService:
    load_env(os.path.join(ROOT, ".env"))
    os.makedirs(os.path.dirname(TRACE), exist_ok=True)
    return ProcureService(DB, LLM(), TRACE)


def svc() -> ProcureService:
    ensure_db()
    return _service(st.session_state.get("svc_version", 0))


def reset(seed: int, skus: int, profile: str):
    """Regenerate the demo ERP (admin only; the caller checks the permission)."""
    old = _service(st.session_state.get("svc_version", 0))
    old.close()
    ensure_db(seed, skus, profile, force=True)
    st.session_state["svc_version"] = st.session_state.get("svc_version", 0) + 1
    st.session_state.pop("last_case", None)


def user() -> str:
    return st.session_state.get("acting_user", "alice")


def role() -> str:
    return svc().role(user()) or "viewer"
