"""Service (API) layer: the only entry point the UI, CLI and FastAPI use.

Role-based access control is enforced here, in code, from the user's role stored in
the ERP `users` table, never from prompts and never from a role the client claims.
The safe-action gate enforces the approval rules a second time underneath.
"""
from __future__ import annotations

import csv
import io
import json
import os
from typing import Optional

from . import agents as A
from .gate import STATES, Gate, GateError
from .llm import LLM
from .models import CaseFile
from .orchestrator import Tracer, is_interrupted, resume_approval, run_case, stream_case
from .query import ask
from .registry import default_registry, default_tool_registry

ALL = {"viewer", "buyer", "approver", "admin"}
PERMISSIONS = {
    "view": ALL,
    "query": ALL,
    "view_audit": ALL,
    "export": ALL,
    "run_case": {"buyer", "approver", "admin"},
    "approve": {"approver", "admin"},
    "reject": {"approver", "admin"},
    "edit": {"approver", "admin"},
    "cancel": {"approver", "admin"},
    "change_settings": {"admin"},
}


class PermissionDenied(Exception):
    pass


class ProcureService:
    def __init__(self, db_path: str, llm: Optional[LLM] = None, trace_path: Optional[str] = None):
        self.db_path = db_path
        self.env = A.Env(db_path, llm or LLM())
        self.gate = Gate(db_path)
        self.tracer = Tracer(trace_path)
        self.cases: dict[str, CaseFile] = {}

    def close(self):
        self.env.close()
        self.gate.close()

    # ------------------------------------------------------------ RBAC
    def role(self, user: str) -> Optional[str]:
        return self.gate.role(user)

    def can(self, user: str, action: str) -> bool:
        return self.role(user) in PERMISSIONS[action]

    def require(self, user: str, action: str):
        if not self.can(user, action):
            self.gate.log_event(user or "anonymous", f"DENIED:{action}", {"role": self.role(user)})
            raise PermissionDenied(f"user '{user}' (role {self.role(user)}) may not {action.replace('_', ' ')}")

    # ------------------------------------------------------------ reads
    def users(self) -> dict:
        return {r["name"]: r["role"] for r in self.gate.db.execute("SELECT name, role FROM users ORDER BY name")}

    def alerts(self, user: str) -> list:
        self.require(user, "view")
        skus = [r[0] for r in self.env.db.execute("SELECT sku FROM items ORDER BY sku")]
        out = [a for a in (A.stock_monitor(self.env, s) for s in skus) if a]
        rank = {"high": 0, "medium": 1, "low": 2}
        return sorted(out, key=lambda a: (rank[a.severity], a.sku))

    def purchase_orders(self, user: str, status: Optional[str] = None) -> list:
        self.require(user, "view")
        q = ("SELECT p.po_id, p.status, s.name supplier, p.supplier_id, l.sku, l.qty, l.unit_price, p.total, "
             "p.created_by, p.approved_by, p.rationale, p.idem_key FROM pos p LEFT JOIN suppliers s ON s.id=p.supplier_id "
             "LEFT JOIN po_lines l USING(po_id)")
        args: tuple = ()
        if status:
            q, args = q + " WHERE p.status=?", (status,)
        return [dict(r) for r in self.gate.db.execute(q + " ORDER BY p.po_id DESC", args)]

    def audit(self, user: str, actor: str = "", action: str = "", po_id: Optional[int] = None) -> list:
        self.require(user, "view_audit")
        rows = self.gate.audit_rows()
        if actor:
            rows = [r for r in rows if r["actor"] == actor]
        if action:
            rows = [r for r in rows if action.lower() in r["action"].lower()]
        if po_id is not None:
            rows = [r for r in rows if r["po_id"] == po_id]
        return rows

    def audit_csv(self, user: str, **filters) -> bytes:
        self.require(user, "export")
        rows = self.audit(user, **filters)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["id", "ts", "actor", "action", "po_id", "detail"])
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().encode("utf-8")

    def po_state_index(self, status: str) -> int:
        return STATES.index(status) if status in STATES else -1

    # ------------------------------------------------------------ agent runs
    def run_case(self, user: str, sku: str, inject_fault: Optional[str] = None) -> CaseFile:
        self.require(user, "run_case")
        self.env.refresh()
        case = run_case(self.env, self.gate, self.tracer, sku, requester=user, inject_fault=inject_fault,
                        interactive=True)
        self.cases[case.task_id] = case
        return case

    def run_case_stream(self, user: str, sku: str, inject_fault: Optional[str] = None):
        """Generator for the UI: yields ("msg", Message) per agent step, then ("case", CaseFile)."""
        self.require(user, "run_case")
        self.env.refresh()
        for kind, item in stream_case(self.env, self.gate, self.tracer, sku, requester=user, inject_fault=inject_fault):
            if kind == "case":
                self.cases[item.task_id] = item
            yield kind, item

    def query(self, user: str, question: str) -> dict:
        self.require(user, "query")
        res = ask(self.env, question)
        if res["status"] == "blocked":
            self.gate.log_event(user, "QUERY_BLOCKED", {"question": question[:200], "reason": res.get("reason")})
        return res

    # ------------------------------------------------------------ approver actions (write path)
    def _task_for(self, po_id: int) -> Optional[str]:
        """Task id of a case still paused at the LangGraph human-approval interrupt."""
        return next((t for t, c in self.cases.items() if c.po_id == po_id and is_interrupted(t)), None)

    def approve(self, user: str, po_id: int, reason: str = "") -> str:
        self.require(user, "approve")
        task = self._task_for(po_id)
        if task:  # resume the LangGraph human-approval interrupt
            case = resume_approval(self.env, self.gate, self.tracer, task, user, True, reason)
            self.cases[task] = case
            return self.gate.status(po_id)
        return self.gate.decide(po_id, user, True, idem_key=f"approve-{po_id}", reason=reason)

    def reject(self, user: str, po_id: int, reason: str = "") -> str:
        self.require(user, "reject")
        task = self._task_for(po_id)
        if task:
            self.cases[task] = resume_approval(self.env, self.gate, self.tracer, task, user, False, reason)
            return self.gate.status(po_id)
        return self.gate.decide(po_id, user, False, idem_key=f"reject-{po_id}", reason=reason)

    def edit(self, user: str, po_id: int, qty: int, reason: str = ""):
        self.require(user, "edit")
        po = self.gate.po(po_id)
        if not po:
            raise GateError(f"unknown PO {po_id}")
        fc = A.forecaster(self.env, po["sku"])

        def validate(q):
            from .models import DraftPO
            d = DraftPO(sku=po["sku"], supplier_id=po["supplier_id"], supplier_name=po["supplier"] or "", qty=q,
                        unit_price=po["unit_price"])
            # budget check must not count this PO's own current total twice
            env = self.env
            v = A.validator(env, d, fc, po["created_by"])
            if any(f.code == "BUDGET" for f in v.failures):
                remaining = env.budget_cap - env.committed_spend() + po["total"]
                fails = [f for f in v.failures if f.code != "BUDGET"]
                if d.total > remaining + 1e-9:
                    fails += [f for f in v.failures if f.code == "BUDGET"]
                v = v.model_copy(update={"failures": fails, "passed": not fails})
            return v
        return self.gate.edit(po_id, user, qty, validate, reason)

    def cancel(self, user: str, po_id: int, reason: str = "") -> str:
        self.require(user, "cancel")
        return self.gate.cancel(po_id, user, idem_key=f"cancel-{po_id}", reason=reason)

    # ------------------------------------------------------------ settings
    def set_weights(self, user: str, weights: dict):
        self.require(user, "change_settings")
        total = sum(weights.values())
        if total <= 0 or set(weights) != {"price", "lead", "reliability"}:
            raise ValueError("weights must be price/lead/reliability with a positive sum")
        self.env.weights = {k: round(v / total, 4) for k, v in weights.items()}
        self.gate.log_event(user, "SETTINGS:supplier_weights", self.env.weights)
        return self.env.weights

    def registry(self) -> dict:
        return {"agents": default_registry.list_agents(), "tools": default_tool_registry.list_tools()}

    # ------------------------------------------------------------ exports
    def po_csv(self, user: str, po_id: int) -> bytes:
        self.require(user, "export")
        po = self.gate.po(po_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["po_id", "status", "supplier", "sku", "qty", "unit_price", "total", "created_by", "approved_by"])
        w.writerow([po[k] for k in ["po_id", "status", "supplier", "sku", "qty", "unit_price", "total", "created_by",
                                    "approved_by"]])
        return buf.getvalue().encode("utf-8")

    def po_pdf(self, user: str, po_id: int) -> bytes:
        self.require(user, "export")
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        po = self.gate.po(po_id)
        trail = self.audit(user, po_id=po_id)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        W, Hh = A4
        c.setFillColorRGB(0.06, 0.36, 0.39)
        c.rect(0, Hh - 30 * mm, W, 30 * mm, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(20 * mm, Hh - 18 * mm, f"Purchase Order #{po['po_id']}")
        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, Hh - 25 * mm, "ProcureAgents - synthetic ERP demo (not a real order)")
        c.setFillColorRGB(0.1, 0.1, 0.1)
        y = Hh - 45 * mm
        for label, val in [("Status", po["status"]), ("Supplier", po["supplier"]), ("SKU", po["sku"]),
                           ("Quantity", po["qty"]), ("Unit price", f"{po['unit_price']:.2f}"),
                           ("Total", f"{po['total']:.2f}"), ("Drafted by", po["created_by"]),
                           ("Approved by", po["approved_by"] or "-")]:
            c.setFont("Helvetica-Bold", 11)
            c.drawString(20 * mm, y, label)
            c.setFont("Helvetica", 11)
            c.drawString(60 * mm, y, str(val))
            y -= 7 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y - 4 * mm, "Rationale")
        c.setFont("Helvetica", 9)
        text = c.beginText(20 * mm, y - 10 * mm)
        words, line = (po["rationale"] or "").split(), ""
        for wd in words:
            if len(line) + len(wd) > 100:
                text.textLine(line)
                line = ""
            line += wd + " "
        text.textLine(line)
        c.drawText(text)
        y2 = text.getY() - 8 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y2, "Audit trail")
        c.setFont("Helvetica", 8)
        for r in trail[:25]:
            y2 -= 5 * mm
            c.drawString(20 * mm, y2, f"{r['ts']}  {r['actor']:<10} {r['action']}")
        c.showPage()
        c.save()
        return buf.getvalue()


def results_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "results"))


def latest_run() -> Optional[str]:
    root = results_root()
    if not os.path.isdir(root):
        return None
    runs = sorted((d for d in os.listdir(root) if os.path.exists(os.path.join(root, d, "summary.json"))),
                  key=lambda d: os.path.getmtime(os.path.join(root, d, "summary.json")))
    return os.path.join(root, runs[-1]) if runs else None


def load_run(path: str) -> dict:
    with open(os.path.join(path, "summary.json"), encoding="utf-8") as f:
        return json.load(f)
