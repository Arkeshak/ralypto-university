"""Whitelisted FastAPI layer over ProcureService (optional; the Streamlit UI calls the service directly).

Run:  uvicorn procure.api:app --app-dir project      (set PROCURE_DB to a generated ERP database)
The acting user is sent in the X-User header; the role is looked up server-side.
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException

from .gate import GateError
from .service import PermissionDenied, ProcureService

app = FastAPI(title="ProcureAgents API", version="1.0")
_svc: dict = {}


def svc() -> ProcureService:
    if "s" not in _svc:
        _svc["s"] = ProcureService(os.environ.get("PROCURE_DB", os.path.join(os.path.dirname(__file__), "..", "data",
                                                                               "demo.db")))
    return _svc["s"]


def user(x_user: str = Header(default="")) -> str:
    return x_user


def _guard(fn):
    try:
        return fn()
    except PermissionDenied as e:
        raise HTTPException(403, str(e))
    except GateError as e:
        raise HTTPException(409, str(e))


@app.get("/alerts")
def alerts(u: str = Depends(user), s: ProcureService = Depends(svc)):
    return _guard(lambda: [a.model_dump() for a in s.alerts(u)])


@app.get("/pos")
def pos(status: str = "", u: str = Depends(user), s: ProcureService = Depends(svc)):
    return _guard(lambda: s.purchase_orders(u, status or None))


@app.post("/cases/{sku}")
def run(sku: str, u: str = Depends(user), s: ProcureService = Depends(svc)):
    return _guard(lambda: s.run_case(u, sku).model_dump(exclude={"trace"}))


@app.post("/pos/{po_id}/approve")
def approve(po_id: int, u: str = Depends(user), s: ProcureService = Depends(svc)):
    return _guard(lambda: {"status": s.approve(u, po_id)})


@app.post("/pos/{po_id}/reject")
def reject(po_id: int, u: str = Depends(user), s: ProcureService = Depends(svc)):
    return _guard(lambda: {"status": s.reject(u, po_id)})


@app.post("/pos/{po_id}/cancel")
def cancel(po_id: int, u: str = Depends(user), s: ProcureService = Depends(svc)):
    return _guard(lambda: {"status": s.cancel(u, po_id)})


@app.get("/query")
def query(q: str, u: str = Depends(user), s: ProcureService = Depends(svc)):
    return _guard(lambda: s.query(u, q))


@app.get("/audit")
def audit(u: str = Depends(user), s: ProcureService = Depends(svc)):
    return _guard(lambda: s.audit(u))
