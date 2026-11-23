"""Safe-action gate: the single write path. RBAC, PO state machine, idempotency, audit."""
from __future__ import annotations

import json
import sqlite3
import time

from .models import CaseFile

ROLES_CAN_DRAFT = {"buyer", "approver", "admin"}
ROLES_CAN_APPROVE = {"approver", "admin"}
TRANSITIONS = {
    "DRAFT": {"VALIDATED", "REJECTED"},
    "VALIDATED": {"PENDING_APPROVAL"},
    "PENDING_APPROVAL": {"APPROVED", "REJECTED"},
    "APPROVED": {"CREATED"},
    "CREATED": {"CANCELLED"},
}


class GateError(Exception):
    pass


class Gate:
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

    def close(self):
        self.db.close()

    # -- helpers
    def role(self, user: str):
        r = self.db.execute("SELECT role FROM users WHERE name=?", (user,)).fetchone()
        return r["role"] if r else None

    def _audit(self, actor, action, po_id, detail):
        self.db.execute("INSERT INTO audit(ts,actor,action,po_id,detail) VALUES (?,?,?,?,?)",
                        (time.strftime("%Y-%m-%dT%H:%M:%S"), actor, action, po_id, json.dumps(detail)))

    def _move(self, po_id, new, actor, detail=None):
        cur = self.db.execute("SELECT status FROM pos WHERE po_id=?", (po_id,)).fetchone()
        if not cur:
            raise GateError(f"unknown PO {po_id}")
        if new not in TRANSITIONS.get(cur["status"], set()):
            raise GateError(f"illegal transition {cur['status']} -> {new}")
        self.db.execute("UPDATE pos SET status=? WHERE po_id=?", (new, po_id))
        self._audit(actor, f"{cur['status']}->{new}", po_id, detail or {})

    def committed_spend(self) -> float:
        r = self.db.execute("SELECT COALESCE(SUM(total),0) s FROM pos WHERE status IN "
                            "('PENDING_APPROVAL','APPROVED','CREATED')").fetchone()
        return float(r["s"])

    # -- write path
    def submit(self, case: CaseFile, idem_key: str) -> int:
        """Agents call this with a *validated* case; creates a PO awaiting human approval."""
        if self.role(case.requester) not in ROLES_CAN_DRAFT:
            raise GateError(f"{case.requester} may not draft POs")
        if not (case.validation and case.validation.passed and case.draft and case.draft.action == "order"):
            raise GateError("only validated order drafts may be submitted")
        old = self.db.execute("SELECT po_id FROM pos WHERE idem_key=?", (idem_key,)).fetchone()
        if old:
            return old["po_id"]  # idempotent retry
        d = case.draft
        cur = self.db.execute("INSERT INTO pos(idem_key,status,supplier_id,total,created_by,rationale) VALUES (?,?,?,?,?,?)",
                              (idem_key, "DRAFT", d.supplier_id, d.total, case.requester, d.rationale))
        po_id = cur.lastrowid
        self.db.execute("INSERT INTO po_lines VALUES (?,?,?,?)", (po_id, d.sku, d.qty, d.unit_price))
        self._audit(case.requester, "DRAFT", po_id, {"task": case.task_id, "sku": d.sku, "qty": d.qty})
        self._move(po_id, "VALIDATED", "validator")
        self._move(po_id, "PENDING_APPROVAL", "gate")
        self.db.commit()
        return po_id

    def decide(self, po_id: int, user: str, approve: bool, idem_key: str = "") -> str:
        if self.role(user) not in ROLES_CAN_APPROVE:
            self._audit(user, "DENIED_decide", po_id, {})
            self.db.commit()
            raise GateError(f"{user} is not an approver")
        status = self.db.execute("SELECT status FROM pos WHERE po_id=?", (po_id,)).fetchone()
        if status and status["status"] in ("CREATED", "REJECTED") and idem_key:
            return status["status"]  # idempotent retry
        if approve:
            self._move(po_id, "APPROVED", user)
            self.db.execute("UPDATE pos SET approved_by=? WHERE po_id=?", (user, po_id))
            self._move(po_id, "CREATED", user)
        else:
            self._move(po_id, "REJECTED", user)
        self.db.commit()
        return self.db.execute("SELECT status FROM pos WHERE po_id=?", (po_id,)).fetchone()["status"]

    def cancel(self, po_id: int, user: str):
        if self.role(user) not in ROLES_CAN_APPROVE:
            raise GateError(f"{user} may not cancel")
        self._move(po_id, "CANCELLED", user)
        self.db.commit()

    def audit_rows(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY id")]
