"""Orchestrator: a LangGraph state graph over the typed case file.

    stock_monitor --(alert?)--> [forecaster || supplier] --> po_agent --> validator
         |                                                     |            |  pass -> gate_submit -> (interrupt) human_approval
         v no alert -> END                      markdown -> END|            |  fail, revision < 2 -> po_reviser -> validator
                                                               v            |  fail otherwise -> escalate (human)
                                                         no supplier -> escalate

Conflict rules implemented here: validator veto with at most MAX_REVISIONS revisions
then escalation; low forecast confidence adds a safety buffer and flags the line for
review; forecaster failure falls back to the deterministic reorder-point policy.
Every node emits a structured Message (task_id, author, inputs, output, confidence,
evidence, latency, mode) to the JSONL trace and to the case file.
"""
from __future__ import annotations

import operator
import threading
import time
import uuid
import warnings
from typing import Annotated, Any, Optional, TypedDict

with warnings.catch_warnings():  # langgraph-checkpoint emits a pending-deprecation notice on import
    import langchain_core  # noqa: F401  (installs its own warning filters first)
    warnings.simplefilter("ignore")
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel  # noqa: E402

from . import agents as A  # noqa: E402
from .gate import Gate, GateError  # noqa: E402
from .models import CaseFile, DraftPO, Forecast, Message  # noqa: E402
from .registry import AgentRegistry, default_registry  # noqa: E402

MAX_REVISIONS = 2
LOW_CONFIDENCE = 0.5
SAFETY_BUFFER = 1.25
_lock = threading.Lock()


class Tracer:
    """Append-only JSONL trace writer (thread-safe)."""

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
    rows = env.db.execute("SELECT * FROM prices WHERE sku=? AND in_stock=1 ORDER BY unit_price, supplier_id",
                          (sku,)).fetchall()
    if not rows:
        return None
    r = rows[0]
    qty = max(r["moq"], int(alert.reorder_point + 14 * alert.avg_daily - alert.on_hand - A._incoming(env, sku)))
    name = env.db.execute("SELECT name FROM suppliers WHERE id=?", (r["supplier_id"],)).fetchone()[0]
    return alert, DraftPO(sku=sku, supplier_id=r["supplier_id"], supplier_name=name, qty=qty, unit_price=r["unit_price"],
                          rationale="Rule-based reorder-point policy (no forecast, cheapest supplier): "
                                    f"ROP {alert.reorder_point} + 14 x {alert.avg_daily} - on hand {alert.on_hand}.")


# ------------------------------------------------------------------ graph state
class State(TypedDict, total=False):
    task_id: str
    sku: str
    requester: str
    inject_fault: Optional[str]
    alert: Any
    forecast: Any
    ranking: Any
    draft: Any
    validation: Any
    revision: int
    status: str
    used_fallback: bool
    review_flag: bool
    po_id: Optional[int]
    decision: Optional[dict]
    notes: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    validations: Annotated[list, operator.add]


class PlanNote(BaseModel):
    """Advisory plan the LLM may write; routing itself is rule-based."""
    priority: str
    note: str


def _ctx(config) -> dict:
    return config["configurable"]


def _msg(state, config, author, inputs, output, t0, conf=None, evidence=()):
    c = _ctx(config)
    m = Message(task_id=state["task_id"], author=author, inputs=inputs, output=output, confidence=conf,
                evidence=[str(e) for e in evidence], latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                mode=c["env"].llm.mode)
    c["tracer"].emit(m)
    return m


def _dump(x):
    return x.model_dump() if hasattr(x, "model_dump") else x


# ------------------------------------------------------------------ nodes
def n_stock_monitor(state: State, config):
    t0 = time.perf_counter()
    c = _ctx(config)
    alert = c["fn"]["stock_monitor"](c["env"], state["sku"])
    if not alert:
        return {"status": "no_action", "alert": None}
    out = {"alert": alert, "trace": [_msg(state, config, "stock_monitor", {"sku": state["sku"]}, alert.model_dump(), t0,
                                          evidence=[alert.evidence])]}
    env = c["env"]
    if env.llm.available:  # orchestrator planning note (advisory, schema-validated, bounded repair)
        t1 = time.perf_counter()
        plan = env.llm.complete_json("You are the orchestrator of a procurement team. Give a priority (low|medium|high) "
                                     "and a one-sentence note for this alert. Do not invent numbers.",
                                     alert.model_dump_json(), PlanNote, max_tokens=150)
        out["trace"].append(_msg(state, config, "orchestrator", {"plan_for": alert.kind},
                                 plan.model_dump() if plan else {"plan": "rule-based route (LLM plan unavailable)"}, t1))
    return out


def n_forecaster(state: State, config):
    t0 = time.perf_counter()
    c = _ctx(config)
    try:
        if state.get("inject_fault") == "forecaster":
            raise RuntimeError("injected forecaster failure")
        fc = c["fn"]["forecaster"](c["env"], state["sku"])
        Forecast.model_validate(fc.model_dump())  # schema check of the agent output
    except Exception as e:  # fallback is applied when the branches join
        return {"used_fallback": True, "notes": [f"forecaster failed ({e}); using reorder-point policy"],
                "trace": [_msg(state, config, "forecaster", {"sku": state["sku"]}, {"error": str(e)}, t0)]}
    return {"forecast": fc, "trace": [_msg(state, config, "forecaster", {"sku": state["sku"]},
                                           {k: v for k, v in fc.model_dump().items() if k != "daily"} |
                                           {"daily_first_7": fc.daily[:7], "mean_28d": round(fc.mean(28), 1)},
                                           t0, conf=fc.confidence, evidence=fc.flags or [fc.method])]}


def n_supplier(state: State, config):
    t0 = time.perf_counter()
    c = _ctx(config)
    rk = c["fn"]["supplier_ranker"](c["env"], state["sku"])
    return {"ranking": rk, "trace": [_msg(state, config, "supplier", {"sku": state["sku"], "weights": rk.weights},
                                          rk.model_dump(), t0, evidence=rk.flagged_notes + rk.excluded)]}


def n_po_agent(state: State, config):
    t0 = time.perf_counter()
    c = _ctx(config)
    env, out = c["env"], {"notes": [], "trace": []}
    if state.get("used_fallback"):
        res = reorder_point_policy(env, state["sku"])
        out["trace"].append(_msg(state, config, "orchestrator", {"fallback": True}, {"policy": "reorder_point"}, t0))
        if not res:
            return out | {"draft": None}
        alert = res[0]
        fc = Forecast(sku=state["sku"], daily=[alert.avg_daily] * A.MAX_HORIZON, sigma_daily=alert.avg_daily ** 0.5,
                      confidence=0.0, method="fallback (recent average)", flags=["fallback"])
        draft = res[1]
        out |= {"forecast": fc, "review_flag": True}
    else:
        fc, mult = state["forecast"], 1.0
        if fc.confidence < LOW_CONFIDENCE:  # conflict rule: low confidence -> buffer + flag
            mult = SAFETY_BUFFER
            out["review_flag"] = True
            out["notes"].append(f"low forecast confidence ({fc.confidence}): +25% safety buffer, flagged for review")
        draft = c["fn"]["po_drafter"](env, state["alert"], fc, state["ranking"], 0, mult)
    if draft is not None:
        out["trace"].append(_msg(state, config, "po_agent", {"alert": state["sku"]}, draft.model_dump(), t0,
                                 conf=(out.get("forecast") or state.get("forecast")).confidence,
                                 evidence=draft.discrepancies))
        out["notes"] += draft.discrepancies
    return out | {"draft": draft, "revision": 0}


def n_validator(state: State, config):
    t0 = time.perf_counter()
    c = _ctx(config)
    v = c["fn"]["validator"](c["env"], state["draft"], state["forecast"], state["requester"])
    for name, ext in c["ext"]:  # plug-in checks registered for the validator stage (may veto)
        extra = ext(c["env"], state["draft"], state["forecast"], state["requester"])
        if extra is not None:
            v = v.model_copy(update={"passed": v.passed and extra.passed,
                                     "failures": v.failures + extra.failures,
                                     "warnings": v.warnings + [f"[{name}] {w}" for w in extra.warnings]})
    return {"validation": v, "validations": [v],
            "trace": [_msg(state, config, "validator", {"draft": state["draft"].model_dump(),
                                                        "pass": len(state.get("validations", [])) + 1},
                           v.model_dump(), t0, evidence=[f.message for f in v.failures] + v.warnings)]}


def n_reviser(state: State, config):
    t0 = time.perf_counter()
    c = _ctx(config)
    env = c["env"]
    rev = state.get("revision", 0) + 1
    remaining = env.budget_cap - env.committed_spend()
    new = c["fn"]["po_reviser"](env, state["draft"], state["validation"].failures, state["ranking"], remaining, rev)
    if new is None:
        return {"revision": rev, "status": "unrevisable"}
    return {"draft": new, "revision": rev,
            "trace": [_msg(state, config, "po_agent", {"revision": rev}, new.model_dump(), t0)]}


def n_escalate(state: State, config):
    t0 = time.perf_counter()
    if state.get("draft") is None:
        note = "no available supplier: escalated to a human buyer"
    else:
        v = state.get("validation")
        note = "validator veto: " + "; ".join(f.message for f in v.failures) if v else "escalated"
    return {"status": "escalated", "notes": [note],
            "trace": [_msg(state, config, "orchestrator", {}, {"escalated_to_human": True, "reason": note}, t0)]}


def n_gate(state: State, config):
    t0 = time.perf_counter()
    c = _ctx(config)
    case = to_case(state)
    try:
        po_id = c["gate"].submit(case, f"{state['task_id']}-{state['sku']}")
        status, notes = "pending_approval", []
    except GateError as e:
        po_id, status, notes = None, "failed", [str(e)]
    return {"po_id": po_id, "status": status, "notes": notes,
            "trace": [_msg(state, config, "gate", {"task": state["task_id"]}, {"po_id": po_id, "status": status}, t0)]}


def n_human(state: State, config):
    """Human Approver. Reached only after the graph is resumed with a decision."""
    t0 = time.perf_counter()
    c = _ctx(config)
    d = state.get("decision") or {}
    try:
        res = c["gate"].decide(state["po_id"], d.get("user", ""), bool(d.get("approve")),
                               idem_key=f"{'approve' if d.get('approve') else 'reject'}-{state['po_id']}",
                               reason=d.get("reason", ""))
        status = "created" if res == "CREATED" else "rejected"
        notes = []
    except GateError as e:
        status, notes = "pending_approval", [f"approval denied: {e}"]
    return {"status": status, "notes": notes,
            "trace": [_msg(state, config, "human_approver", d, {"status": status}, t0)]}


# ------------------------------------------------------------------ routing
def r_after_monitor(state: State):
    return END if state.get("status") == "no_action" else ["forecaster", "supplier"]


def r_after_po(state: State):
    d = state.get("draft")
    if d is None:
        return "escalate"
    return END if d.action == "markdown" else "validator"


def r_after_validator(state: State):
    if state["validation"].passed:
        return "gate_submit"
    return "po_reviser" if state.get("revision", 0) < MAX_REVISIONS else "escalate"


def r_after_reviser(state: State):
    return "escalate" if state.get("status") == "unrevisable" else "validator"


def build_graph(interactive: bool = False):
    g = StateGraph(State)
    g.add_node("stock_monitor", n_stock_monitor)
    g.add_node("forecaster", n_forecaster)
    g.add_node("supplier", n_supplier)
    g.add_node("po_agent", n_po_agent)
    g.add_node("validator", n_validator)
    g.add_node("po_reviser", n_reviser)
    g.add_node("escalate", n_escalate)
    g.add_node("gate_submit", n_gate)
    g.add_edge(START, "stock_monitor")
    g.add_conditional_edges("stock_monitor", r_after_monitor, ["forecaster", "supplier", END])
    g.add_edge(["forecaster", "supplier"], "po_agent")  # join: waits for both parallel branches
    g.add_conditional_edges("po_agent", r_after_po, ["validator", "escalate", END])
    g.add_conditional_edges("validator", r_after_validator, ["gate_submit", "po_reviser", "escalate"])
    g.add_conditional_edges("po_reviser", r_after_reviser, ["validator", "escalate"])
    g.add_edge("escalate", END)
    if interactive:
        g.add_node("human_approval", n_human)
        g.add_conditional_edges("gate_submit", lambda s: "human_approval" if s.get("po_id") else END,
                                ["human_approval", END])
        g.add_edge("human_approval", END)
        return g.compile(checkpointer=MemorySaver(), interrupt_before=["human_approval"])
    g.add_edge("gate_submit", END)
    return g.compile()


_GRAPHS: dict = {}


def graph(interactive: bool = False):
    if interactive not in _GRAPHS:
        _GRAPHS[interactive] = build_graph(interactive)
    return _GRAPHS[interactive]


def mermaid() -> str:
    """Workflow diagram generated from the compiled graph itself."""
    return graph(True).get_graph().draw_mermaid()


# ------------------------------------------------------------------ public API
def to_case(state: dict, latency_s: float = 0.0, mode: str = "") -> CaseFile:
    status = state.get("status") or "open"
    d = state.get("draft")
    if status in ("open", "unrevisable"):
        status = "no_action" if d is not None and d.action == "markdown" else "escalated"
    return CaseFile(task_id=state["task_id"], sku=state["sku"], requester=state["requester"], status=status,
                    alert=state.get("alert"), forecast=state.get("forecast"), ranking=state.get("ranking"),
                    draft=d, validation=state.get("validation"), validations=state.get("validations", []),
                    po_id=state.get("po_id"), review_flag=bool(state.get("review_flag")),
                    used_fallback=bool(state.get("used_fallback")), notes=list(state.get("notes", [])),
                    trace=list(state.get("trace", [])), latency_s=latency_s, mode=mode)


def _functions(reg: AgentRegistry) -> dict:
    names = ["stock_monitor", "forecaster", "supplier_ranker", "po_drafter", "po_reviser", "validator"]
    return {n: reg.get(n) or getattr(A, n) for n in names}


def run_case(env: A.Env, gate: Gate, tracer: Tracer, sku: str, requester: str = "alice",
             inject_fault: str | None = None, registry: AgentRegistry | None = None,
             interactive: bool = False) -> CaseFile:
    """Run one case through the graph. Stops at PENDING_APPROVAL (the human decides later)."""
    t0 = time.perf_counter()
    task_id = uuid.uuid4().hex[:8]
    reg = registry or default_registry
    cfg = {"configurable": {"env": env, "gate": gate, "tracer": tracer, "fn": _functions(reg),
                            "ext": reg.extensions("validator"), "thread_id": task_id}, "recursion_limit": 40}
    init = {"task_id": task_id, "sku": sku, "requester": requester, "inject_fault": inject_fault, "revision": 0,
            "notes": [], "trace": [], "validations": []}
    state = graph(interactive).invoke(init, cfg)
    if interactive:
        _PENDING[task_id] = cfg
    if env.llm.failures and env.llm.available:
        state.setdefault("notes", []).append(f"{env.llm.failures} LLM call(s) failed; deterministic text used")
    return to_case(state, time.perf_counter() - t0, env.llm.mode)


_PENDING: dict = {}


def is_interrupted(task_id: str) -> bool:
    return task_id in _PENDING


def resume_approval(env: A.Env, gate: Gate, tracer: Tracer, task_id: str, user: str, approve: bool,
                    reason: str = "") -> CaseFile:
    """Resume an interactive case at the human-approval interrupt."""
    cfg = _PENDING.get(task_id)
    if cfg is None:
        raise GateError("no interrupted case with this task id")
    cfg["configurable"].update(env=env, gate=gate, tracer=tracer)
    g = graph(True)
    g.update_state(cfg, {"decision": {"user": user, "approve": approve, "reason": reason}})
    state = g.invoke(None, cfg)
    if state.get("status") in ("created", "rejected"):
        _PENDING.pop(task_id, None)
    return to_case(state, 0.0, env.llm.mode)
