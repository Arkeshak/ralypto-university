"""Safe-action gate: the single write path.

PO state machine:   DRAFT -> VALIDATED -> PENDING_APPROVAL -> APPROVED -> CREATED (-> CANCELLED | RECEIVED)
                    DRAFT / PENDING_APPROVAL -> REJECTED
Only approver/admin users may trigger APPROVED and CREATED (and the CANCELLED rollback).
Every write runs in one transaction, carries an idempotency key and leaves an
append-only audit row naming who or what decided it.
"""
from __future__ import annotations

import functools
import json
import sqlite3
import threading
import time
from typing import Callable, Optional

from .models import CaseFile, Validation

ROLES_CAN_DRAFT = {"buyer", "approver", "admin"}
ROLES_CAN_APPROVE = {"approver", "admin"}
TRANSITIONS = {
    "DRAFT": {"VALIDATED", "REJECTED"},
    "VALIDATED": {"PENDING_APPROVAL"},
    "PENDING_APPROVAL": {"APPROVED", "REJECTED"},
    "APPROVED": {"CREATED"},
    "CREATED": {"CANCELLED", "RECEIVED"},
}
STATES = ["DRAFT", "VALIDATED", "PENDING_APPROVAL", "APPROVED", "CREATED"]


class GateError(Exception):
    pass


class Gate:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._lock = threading.RLock()  # one connection shared by parallel cases: serialise every use
        self.db.row_factory = sqlite3.Row

    def close(self):
        self.db.close()

    # ------------------------------------------------------------ helpers
    def role(self, user: str):
        r = self.db.execute("SELECT role FROM users WHERE name=?", (user,)).fetchone()
        return r["role"] if r else None

    def _audit(self, actor, action, po_id, detail):
        self.db.execute("INSERT INTO audit(ts,actor,action,po_id,detail) VALUES (?,?,?,?,?)",
                        (time.strftime("%Y-%m-%dT%H:%M:%S"), actor, action, po_id, json.dumps(detail, default=str)))

    def log_event(self, actor: str, action: str, detail: dict, po_id: Optional[int] = None):
        """Append a non-transition event (denied request, blocked query, settings change)."""
        with self.db:
            self._audit(actor, action, po_id, detail)

    def status(self, po_id: int) -> Optional[str]:
        r = self.db.execute("SELECT status FROM pos WHERE po_id=?", (po_id,)).fetchone()
        return r["status"] if r else None

    def _move(self, po_id, new, actor, detail=None):
        cur = self.status(po_id)
        if cur is None:
            raise GateError(f"unknown PO {po_id}")
        if new not in TRANSITIONS.get(cur, set()):
            raise GateError(f"illegal transition {cur} -> {new}")
        self.db.execute("UPDATE pos SET status=? WHERE po_id=?", (new, po_id))
        self._audit(actor, f"{cur}->{new}", po_id, detail or {})

    def _seen(self, idem_key: Optional[str]):
        if not idem_key:
            return None
        r = self.db.execute("SELECT result FROM gate_ops WHERE idem_key=?", (idem_key,)).fetchone()
        return r["result"] if r else None

    def _remember(self, idem_key: Optional[str], po_id: int, result: str):
        if idem_key:
            self.db.execute("INSERT INTO gate_ops VALUES (?,?,?)", (idem_key, po_id, result))

    def _deny(self, user, action, po_id, why):
        self.log_event(user, f"DENIED:{action}", {"reason": why}, po_id)
        raise GateError(why)

    def committed_spend(self) -> float:
        r = self.db.execute("SELECT COALESCE(SUM(total),0) s FROM pos WHERE status IN "
                            "('PENDING_APPROVAL','APPROVED','CREATED','RECEIVED')").fetchone()
        return float(r["s"])

    # ------------------------------------------------------------ write path
    def submit(self, case: CaseFile, idem_key: str) -> int:
        """Agents call this with a *validated* case; creates a PO awaiting human approval."""
        if self.role(case.requester) not in ROLES_CAN_DRAFT:
            self._deny(case.requester, "submit", None, f"{case.requester} may not draft POs")
        if not (case.validation and case.validation.passed and case.draft and case.draft.action == "order"):
            self._deny(case.requester, "submit", None, "only validated order drafts may be submitted")
        old = self.db.execute("SELECT po_id FROM pos WHERE idem_key=?", (idem_key,)).fetchone()
        if old:
            return old["po_id"]  # idempotent retry
        d = case.draft
        today = self.db.execute("SELECT value FROM meta WHERE key='today_day'").fetchone()
        with self.db:  # one transaction: all or nothing
            cur = self.db.execute("INSERT INTO pos(idem_key,status,supplier_id,total,created_by,rationale,created_day) "
                                  "VALUES (?,?,?,?,?,?,?)", (idem_key, "DRAFT", d.supplier_id, d.total, case.requester,
                                                            d.rationale, int(today[0]) if today else None))
            po_id = cur.lastrowid
            self.db.execute("INSERT INTO po_lines VALUES (?,?,?,?)", (po_id, d.sku, d.qty, d.unit_price))
            self._audit(case.requester, "DRAFT", po_id, {"task": case.task_id, "sku": d.sku, "qty": d.qty,
                                                         "supplier": d.supplier_name, "total": d.total})
            self._move(po_id, "VALIDATED", "validator",
                       {"warnings": case.validation.warnings, "passes": len(case.validations) or 1})
            self._move(po_id, "PENDING_APPROVAL", "gate", {"review_flag": case.review_flag})
        return po_id or 0

    def decide(self, po_id: int, user: str, approve: bool, idem_key: str = "", reason: str = "") -> str:
        """Approver decision. Approve = PENDING_APPROVAL -> APPROVED -> CREATED; reject = -> REJECTED."""
        prior = self._seen(idem_key)
        if prior:
            return prior  # idempotent retry: no second write
        if self.role(user) not in ROLES_CAN_APPROVE:
            self._deny(user, "decide", po_id, f"{user} is not an approver")
        with self.db:
            if approve:
                self._move(po_id, "APPROVED", user, {"reason": reason})
                self.db.execute("UPDATE pos SET approved_by=? WHERE po_id=?", (user, po_id))
                self._move(po_id, "CREATED", user, {"note": "PO created in ERP"})
            else:
                self._move(po_id, "REJECTED", user, {"reason": reason})
            result = self.status(po_id) or ""
            self._remember(idem_key, po_id, result)
        return result

    def edit(self, po_id: int, user: str, qty: int, validate: Callable[[int], Validation], reason: str = "") -> Validation:
        """Approver edits the quantity of a pending PO. The edit is re-validated before it is stored."""
        if self.role(user) not in ROLES_CAN_APPROVE:
            self._deny(user, "edit", po_id, f"{user} may not edit POs")
        if self.status(po_id) != "PENDING_APPROVAL":
            raise GateError("only pending POs can be edited")
        v = validate(qty)
        if not v.passed:
            self.log_event(user, "EDIT_REJECTED_BY_VALIDATOR", {"qty": qty, "failures": [f.message for f in v.failures]},
                           po_id)
            return v
        line = self.db.execute("SELECT qty, unit_price FROM po_lines WHERE po_id=?", (po_id,)).fetchone()
        with self.db:
            self.db.execute("UPDATE po_lines SET qty=? WHERE po_id=?", (qty, po_id))
            self.db.execute("UPDATE pos SET total=? WHERE po_id=?", (round(qty * line["unit_price"], 2), po_id))
            self._audit(user, "EDIT(override)", po_id, {"old_qty": line["qty"], "new_qty": qty, "reason": reason})
        return v

    def cancel(self, po_id: int, user: str, idem_key: str = "", reason: str = "") -> str:
        """Rollback: a created PO can be cancelled by an approver."""
        prior = self._seen(idem_key)
        if prior:
            return prior
        if self.role(user) not in ROLES_CAN_APPROVE:
            self._deny(user, "cancel", po_id, f"{user} may not cancel")
        with self.db:
            self._move(po_id, "CANCELLED", user, {"reason": reason})
            self._remember(idem_key, po_id, "CANCELLED")
        return "CANCELLED"

    def receive(self, po_id: int, user: str) -> str:
        """Goods receipt (used by the replay simulator's warehouse clerk, an admin user)."""
        if self.role(user) != "admin":
            self._deny(user, "receive", po_id, f"{user} may not book goods receipts")
        with self.db:
            self._move(po_id, "RECEIVED", user, {"note": "goods received"})
        return "RECEIVED"

    # ------------------------------------------------------------ reads
    def audit_rows(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY id")]

    def po(self, po_id: int) -> Optional[dict]:
        r = self.db.execute("SELECT p.*, s.name supplier, l.sku, l.qty, l.unit_price FROM pos p LEFT JOIN suppliers s "
                            "ON s.id=p.supplier_id LEFT JOIN po_lines l USING(po_id) WHERE p.po_id=?", (po_id,)).fetchone()
        return dict(r) if r else None


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        with self._lock:
            return fn(self, *a, **kw)
    return wrapper


for _name in ["role", "log_event", "status", "committed_spend", "submit", "decide", "edit", "cancel", "receive",
              "audit_rows", "po"]:
    setattr(Gate, _name, _locked(getattr(Gate, _name)))
