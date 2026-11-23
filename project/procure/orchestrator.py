"""Orchestrator: routes a case through the agents, runs branches in parallel,
settles conflicts, escalates to a human, and writes a JSONL trace."""
from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import agents as A
from .gate import Gate, GateError
from .models import CaseFile, Message
from .registry import AgentRegistry, default_registry

MAX_REVISIONS = 2
_lock = threading.Lock()


class Tracer:
    def __init__(self, path: str | None):
        self.path = path

    def emit(self, msg: Message):
        if self.path:
            with _lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(msg.model_dump_json() + "\n")


def reorder_point_policy(env: A.Env, sku: str):
    """Deterministic fallback / rule-based floor: order up to ROP + 14d of recent demand, cheapest in-stock supplier."""
    alert = A.stock_monitor(env, sku)
    if not alert:
        return None
    rows = env.db.execute("SELECT * FROM prices WHERE sku=? AND in_stock=1 ORDER BY unit_price", (sku,)).fetchall()
    if not rows:
        return None
    r = rows[0]
    qty = max(r["moq"], int(alert.reorder_point + 14 * alert.avg_daily - alert.on_hand))
    from .models import DraftPO
    name = env.db.execute("SELECT name FROM suppliers WHERE id=?", (r["supplier_id"],)).fetchone()[0]
    return alert, DraftPO(sku=sku, supplier_id=r["supplier_id"], supplier_name=name, qty=qty, unit_price=r["unit_price"],
                          rationale="Rule-based reorder-point policy (no forecast, cheapest supplier).")


def run_case(env: A.Env, gate: Gate, tracer: Tracer, sku: str, requester: str = "alice",
             inject_fault: str | None = None, registry: AgentRegistry | None = None) -> CaseFile:
    reg = registry or default_registry
    fn_monitor = reg.get("stock_monitor") or A.stock_monitor
    fn_forecast = reg.get("forecaster") or A.forecaster
    fn_supplier = reg.get("supplier_ranker") or A.supplier_ranker
    fn_po = reg.get("po_drafter") or A.po_drafter
    fn_reviser = reg.get("po_reviser") or A.po_reviser
    fn_validator = reg.get("validator") or A.validator

    case = CaseFile(task_id=uuid.uuid4().hex[:8], sku=sku, requester=requester)

    def log(author, inputs, output, conf=None, evidence=()):
        tracer.emit(Message(task_id=case.task_id, author=author, inputs=inputs, output=output, confidence=conf,
                            evidence=list(evidence)))

    # 1. Stock Monitor
    case.alert = fn_monitor(env, sku)
    if not case.alert:
        case.status = "no_action"
        return case
    log("stock_monitor", {"sku": sku}, case.alert.model_dump(), evidence=[case.alert.evidence])

    # 2. Forecasting and Supplier agents in parallel
    def do_forecast():
        if inject_fault == "forecaster":
            raise RuntimeError("injected forecaster failure")
        return fn_forecast(env, sku)

    with ThreadPoolExecutor(2) as ex:
        f_fc, f_sup = ex.submit(do_forecast), ex.submit(fn_supplier, env, sku)
        try:
            case.forecast = f_fc.result()
        except Exception as e:  # fallback: deterministic reorder-point policy
            case.used_fallback = True
            case.notes.append(f"forecaster failed ({e}); using reorder-point policy")
        case.ranking = f_sup.result()
    if case.used_fallback:
        res = reorder_point_policy(env, sku)
        log("orchestrator", {"fallback": True}, {"reason": case.notes[-1]})
        if not res:
            case.status = "escalated"
            return case
        case.draft = res[1]
        from .models import Forecast
        case.forecast = Forecast(sku=sku, daily=[res[0].avg_daily] * A.MAX_HORIZON, sigma_daily=res[0].avg_daily ** 0.5,
                                 confidence=0.0, method="fallback", flags=["fallback"])
    else:
        log("forecaster", {"sku": sku}, case.forecast.model_dump(), conf=case.forecast.confidence,
            evidence=case.forecast.flags)
        log("supplier", {"sku": sku}, case.ranking.model_dump(), evidence=case.ranking.flagged_notes)
        if case.forecast.confidence < 0.5:  # conflict rule: low confidence -> buffer + flag
            case.review_flag = True
            case.notes.append("low forecast confidence: +25% safety buffer, flagged for review")
        mult = 1.25 if case.review_flag else 1.0
        case.draft = fn_po(env, case.alert, case.forecast, case.ranking, 0, mult)
    if case.draft is None:
        case.status = "escalated"
        case.notes.append("no available supplier")
        return case
    log("po_agent", {"alert": case.alert.sku}, case.draft.model_dump())
    if case.draft.action == "markdown":
        case.status = "no_action"
        case.notes.append("markdown recommended instead of reorder")
        return case

    # 3. Validator loop with bounded revisions
    for rev in range(MAX_REVISIONS + 1):
        case.validation = fn_validator(env, case.draft, case.forecast, requester)
        log("validator", {"draft": case.draft.model_dump()}, case.validation.model_dump())
        if case.validation.passed:
            break
        if rev == MAX_REVISIONS:
            break
        remaining = env.budget_cap - env.committed_spend()
        revised = fn_reviser(env, case.draft, case.validation.failures, case.ranking, remaining, rev + 1)
        if revised is None:
            break
        case.draft = revised
        log("po_agent", {"revision": rev + 1}, case.draft.model_dump())
    if not case.validation.passed:
        case.status = "escalated"
        case.notes.append("validator veto: " + "; ".join(f.message for f in case.validation.failures))
        log("orchestrator", {}, {"escalated_to_human": True})
        return case

    # 4. Safe-action gate -> pending human approval
    try:
        case.po_id = gate.submit(case, f"{case.task_id}-{sku}")
        case.status = "pending_approval"
    except GateError as e:
        case.status = "failed"
        case.notes.append(str(e))
    log("gate", {"task": case.task_id}, {"po_id": case.po_id, "status": case.status})
    return case
