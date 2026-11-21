"""System B (single agent, LLM tool-calling loop) and System D (rule-based floor).

B uses the same LLM, tools (same forecaster/supplier code), validator and approval gate
as the multi-agent system; only the architecture differs. It needs a live LLM and
returns None without one (it is never faked).
"""
from __future__ import annotations

import json
import uuid

from . import agents as A
from .gate import Gate, GateError
from .models import CaseFile, DraftPO
from .orchestrator import Tracer, reorder_point_policy

SYSTEM = ("You are a procurement agent. Decide whether and how much to reorder for one SKU. Use tools by replying with "
          'JSON only: {"tool": "alert|forecast|suppliers", "args": {}} or finish with '
          '{"final": {"supplier_id": int, "qty": int, "rationale": str}} or {"final": null} for no order. '
          "Quantities should cover forecast demand over lead time + review period plus safety stock, respect MOQ.")


def single_agent(env: A.Env, gate: Gate, tracer: Tracer, sku: str, requester: str = "alice", max_steps: int = 8):
    llm = env.llm
    if not llm.available:
        return None
    case = CaseFile(task_id=uuid.uuid4().hex[:8], sku=sku, requester=requester)
    transcript = f"SKU: {sku}. Review period days: {env.profile['review']}. Service z: {env.profile['z']}.\n"
    for _ in range(max_steps):
        out = llm.complete(SYSTEM, transcript, 500)
        if not out:
            case.status = "failed"
            return case
        try:
            msg = json.loads(out[out.index("{"): out.rindex("}") + 1])
        except Exception:
            transcript += "\nInvalid JSON; reply with JSON only."
            continue
        if "final" in msg:
            fin = msg["final"]
            if not fin:
                case.status = "no_action"
                return case
            case.alert = A.stock_monitor(env, sku)
            case.forecast = A.forecaster(env, sku)
            row = env.db.execute("SELECT p.*, s.name FROM prices p JOIN suppliers s ON s.id=p.supplier_id WHERE p.sku=? "
                                 "AND p.supplier_id=?", (sku, fin.get("supplier_id"))).fetchone()
            if not row:
                case.status = "escalated"
                return case
            case.draft = DraftPO(sku=sku, supplier_id=row["supplier_id"], supplier_name=row["name"], qty=int(fin["qty"]),
                                 unit_price=row["unit_price"], rationale=str(fin.get("rationale", "")))
            case.validation = A.validator(env, case.draft, case.forecast, requester)
            if not case.validation.passed:
                case.status = "escalated"
                return case
            try:
                case.po_id = gate.submit(case, f"{case.task_id}-{sku}")
                case.status = "pending_approval"
            except GateError as e:
                case.status, case.notes = "failed", [str(e)]
            return case
        tool = msg.get("tool")
        if tool == "alert":
            res = A.stock_monitor(env, sku)
            res = res.model_dump() if res else None
        elif tool == "forecast":
            fc = A.forecaster(env, sku)
            res = {"daily_first_28": fc.daily, "sigma_daily": fc.sigma_daily, "confidence": fc.confidence}
        elif tool == "suppliers":
            rk = A.supplier_ranker(env, sku)
            res = [o.model_dump() for o in rk.options]
        else:
            res = "unknown tool"
        transcript += f"\nTool {tool} result: {json.dumps(res)}"
    case.status = "failed"
    return case


def rule_based(env: A.Env, gate: Gate, sku: str, requester: str = "alice"):
    """System D: deterministic reorder-point policy, same validator + gate, no LLM, no forecast."""
    res = reorder_point_policy(env, sku)
    case = CaseFile(task_id=uuid.uuid4().hex[:8], sku=sku, requester=requester)
    if not res:
        case.status = "no_action"
        return case
    case.alert, case.draft = res
    case.forecast = A.forecaster(env, sku)  # only used by the validator's sanity bound
    case.validation = A.validator(env, case.draft, case.forecast, requester)
    if not case.validation.passed:
        case.status = "escalated"
        return case
    case.po_id = gate.submit(case, f"{case.task_id}-{sku}")
    case.status = "pending_approval"
    return case
