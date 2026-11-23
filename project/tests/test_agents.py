"""Validator rules, conflict rules, fallback, LangGraph structure, LLM wrapper, forecasting, benchmark."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from procure import agents as A  # noqa: E402
from procure import forecasting as F  # noqa: E402
from procure.data import generate  # noqa: E402
from procure.gate import Gate  # noqa: E402
from procure.llm import LLM, OFFLINE_LABEL  # noqa: E402
from procure.models import DraftPO, Forecast, Validation  # noqa: E402
from procure.orchestrator import MAX_REVISIONS, Tracer, graph, run_case  # noqa: E402
from procure.registry import default_registry  # noqa: E402


@pytest.fixture
def env_gate(tmp_path):
    p = str(tmp_path / "a.db")
    w = generate(p, 4, 25)
    env, gate = A.Env(p), Gate(p)
    yield w, env, gate
    env.close()
    gate.close()


def alert_sku(w, env):
    return next(s for s in w.truth if A.stock_monitor(env, s))


def good_draft(env, sku):
    row = env.db.execute("SELECT p.*, s.name FROM prices p JOIN suppliers s ON s.id=p.supplier_id WHERE p.sku=? AND "
                         "p.in_stock=1", (sku,)).fetchone()
    return DraftPO(sku=sku, supplier_id=row["supplier_id"], supplier_name=row["name"], qty=max(row["moq"], 10),
                   unit_price=row["unit_price"]), row


# ---------------------------------------------------------------- validator rules
def test_validator_passes_a_clean_draft(env_gate):
    w, env, _ = env_gate
    sku = alert_sku(w, env)
    d, _ = good_draft(env, sku)
    assert A.validator(env, d, A.forecaster(env, sku), "alice").passed


@pytest.mark.parametrize("change,code", [
    ({"qty": 0}, "SANITY"), ({"unit_price": 0.01}, "PRICE"), ({"qty": 10 ** 6}, "SANITY"),
    ({"supplier_id": 999}, "PRICE")])
def test_validator_rules(env_gate, change, code):
    w, env, _ = env_gate
    sku = alert_sku(w, env)
    d, _ = good_draft(env, sku)
    v = A.validator(env, d.model_copy(update=change), A.forecaster(env, sku), "alice")
    assert not v.passed and code in {f.code for f in v.failures}


def test_validator_moq_role_and_budget(tmp_path):
    p = str(tmp_path / "m.db")
    w = generate(p, 4, 25, moq_scale=50, budget_cap=10.0)
    env = A.Env(p)
    sku = alert_sku(w, env)
    d, row = good_draft(env, sku)
    d = d.model_copy(update={"qty": row["moq"] - 1})
    v = A.validator(env, d, A.forecaster(env, sku), "carol")
    assert {"MOQ", "ROLE", "BUDGET"} <= {f.code for f in v.failures}
    env.close()


def test_low_confidence_warning(env_gate):
    w, env, _ = env_gate
    sku = alert_sku(w, env)
    d, _ = good_draft(env, sku)
    fc = Forecast(sku=sku, daily=[1.0] * 28, sigma_daily=1.0, confidence=0.2, method="x")
    assert any("low forecast confidence" in x for x in A.validator(env, d, fc, "alice").warnings)


# ---------------------------------------------------------------- conflict rules
def test_revisions_bounded_then_escalate(env_gate):
    w, env, gate = env_gate
    reg = default_registry.copy()
    from procure.models import Failure
    reg.register("validator", lambda e, d, f, r: Validation(passed=False, failures=[Failure(code="MOQ", message="x")]))
    c = run_case(env, gate, Tracer(None), alert_sku(w, env), registry=reg)
    assert c.status == "escalated" and len(c.validations) == MAX_REVISIONS + 1 and c.po_id is None


def test_low_confidence_adds_buffer_and_flag(tmp_path):
    p = str(tmp_path / "n.db")
    w = generate(p, 4, 30, new_item_frac=1.0)
    env, gate = A.Env(p), Gate(p)
    cases = [run_case(env, gate, Tracer(None), s) for s in w.truth]
    flagged = [c for c in cases if c.forecast and c.forecast.confidence < 0.5 and c.status != "no_action"]
    assert flagged and all(c.review_flag for c in flagged)
    assert any("safety buffer" in n for c in flagged for n in c.notes)
    env.close()
    gate.close()


def test_weighted_score_respects_weights(env_gate):
    w, env, _ = env_gate
    sku = alert_sku(w, env)
    cheap = A.supplier_ranker(env, sku, {"price": 1.0, "lead": 0.0, "reliability": 0.0}).options[0]
    reliable = A.supplier_ranker(env, sku, {"price": 0.0, "lead": 0.0, "reliability": 1.0}).options[0]
    rows = env.db.execute("SELECT p.unit_price, s.reliability FROM prices p JOIN suppliers s ON s.id=p.supplier_id "
                          "WHERE p.sku=? AND p.in_stock=1", (sku,)).fetchall()
    assert cheap.unit_price == min(r[0] for r in rows) and reliable.reliability == max(r[1] for r in rows)


def test_llm_text_with_wrong_numbers_is_discarded_and_logged(env_gate):
    w, env, _ = env_gate

    class LyingLLM(LLM):
        @property
        def available(self):
            return True

        def complete(self, system, prompt, max_tokens=400):
            return "Order 99999 units now."
    env.llm = LyingLLM()
    sku = alert_sku(w, env)
    d = A.po_drafter(env, A.stock_monitor(env, sku), A.forecaster(env, sku), A.supplier_ranker(env, sku))
    assert d.qty != 99999 and "99999" not in d.rationale and d.discrepancies


# ---------------------------------------------------------------- fallback and faults
def test_forecaster_failure_falls_back_to_reorder_point(env_gate):
    w, env, gate = env_gate
    c = run_case(env, gate, Tracer(None), alert_sku(w, env), inject_fault="forecaster")
    assert c.used_fallback and c.status in ("pending_approval", "escalated") and c.review_flag


def test_llm_timeout_does_not_break_case(env_gate):
    w, env, gate = env_gate

    class DownLLM(LLM):
        @property
        def available(self):
            return True
    env.llm = DownLLM(provider="openai", model="m", base_url="http://127.0.0.1:9", fault="timeout")
    c = run_case(env, gate, Tracer(None), alert_sku(w, env))
    assert c.status == "pending_approval" and env.llm.failures > 0


def test_offline_mode_is_labelled_and_never_calls():
    llm = LLM(provider="offline")
    assert not llm.available and llm.mode == OFFLINE_LABEL and llm.complete("s", "p") is None


def test_complete_json_bounded_repair():
    from pydantic import BaseModel

    class P(BaseModel):
        x: int
    replies = iter(["not json", '{"x": "nope"}', '{"x": 3}'])

    class Flaky(LLM):
        @property
        def available(self):
            return True

        def complete(self, system, prompt, max_tokens=400):
            return next(replies)
    llm = Flaky()
    assert llm.complete_json("s", "p", P, max_repairs=2).x == 3 and llm.repairs == 2
    replies = iter(["bad"] * 5)
    assert Flaky().complete_json("s", "p", P, max_repairs=1) is None


# ---------------------------------------------------------------- graph and messages
def test_graph_has_parallel_branches_and_interrupt():
    g = graph(True).get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert ("stock_monitor", "forecaster") in edges and ("stock_monitor", "supplier") in edges
    assert ("forecaster", "po_agent") in edges and ("supplier", "po_agent") in edges
    assert "human_approval" in {n for n in g.nodes}


def test_messages_are_structured_and_traced(env_gate, tmp_path):
    w, env, gate = env_gate
    trace = str(tmp_path / "t.jsonl")
    c = run_case(env, gate, Tracer(trace), alert_sku(w, env))
    rows = [json.loads(x) for x in open(trace, encoding="utf-8")]
    assert {m.author for m in c.trace} >= {"stock_monitor", "forecaster", "supplier", "po_agent", "validator", "gate"}
    for r in rows:
        assert {"task_id", "author", "inputs", "output", "confidence", "evidence", "latency_ms", "mode"} <= set(r)
        assert r["task_id"] == c.task_id


def test_interactive_interrupt_and_resume(tmp_path):
    from procure.service import ProcureService
    p = str(tmp_path / "x.db")
    generate(p, 6, 20)
    s = ProcureService(p)
    c = s.run_case("alice", s.alerts("alice")[0].sku)
    assert c.status == "pending_approval"
    s.approve("bob", c.po_id)
    assert s.cases[c.task_id].status == "created" and s.cases[c.task_id].trace[-1].author == "human_approver"
    s.close()


def test_extension_agent_can_veto(env_gate):
    w, env, gate = env_gate
    from procure.models import Failure
    reg = default_registry.copy()
    reg.register_extension("no_fastcheap", lambda e, d, f, r: Validation(
        passed=d.supplier_id != 1, failures=[] if d.supplier_id != 1 else [Failure(code="POLICY", message="banned")]))
    for s in [x for x in w.truth if A.stock_monitor(env, x)][:8]:
        c = run_case(env, gate, Tracer(None), s, registry=reg)
        if c.status == "pending_approval":
            assert c.draft.supplier_id != 1
    assert any("extension" in k for k in reg.list_agents())


# ---------------------------------------------------------------- forecasting
def test_wape_mape():
    assert F.wape([10, 10], [12, 8]) == pytest.approx(0.2)
    assert F.mape([10, 0, 5], [12, 3, 5]) == pytest.approx(0.1)
    assert F.wape([0, 0], [1, 1]) == 0.0


def test_lightgbm_trains_and_beats_naive(tmp_path):
    p = str(tmp_path / "f.db")
    generate(p, 2, 30)
    env = A.Env(p)
    cut = env.today - 28
    H = env.all_histories(env.today)
    m = F.LGBMForecaster({s: {d: q for d, q in h.items() if d < cut} for s, h in H.items()}, env.all_promos(), cut)
    a, f_l, f_n = [], [], []
    for s, h in H.items():
        hh = {d: q for d, q in h.items() if d < cut}
        if len(hh) < 90:
            continue
        a += [h.get(d, 0) for d in range(cut, env.today)]
        f_l += m.predict(hh, env.all_promos().get(s, set()))[0]
        f_n += F.naive(hh, cut)
    assert F.wape(a, f_l) < F.wape(a, f_n)
    assert A.forecaster(env, next(iter(H))).method.startswith("LightGBM")
    env.close()


def test_censored_stockout_days_excluded(tmp_path):
    import sqlite3
    p = str(tmp_path / "c.db")
    generate(p, 2, 5)
    db = sqlite3.connect(p)
    db.executemany("INSERT INTO stockouts VALUES (?,?)", [("SKU-0000", d) for d in range(150, 180)])
    db.commit()
    db.close()
    env = A.Env(p)
    fc = A.forecaster(env, "SKU-0000")
    assert any(f.startswith("excluded_30_stockout") for f in fc.flags)
    env.close()


def test_ets_and_seasonal_baselines_shapes():
    hist = {d: 10 + (d % 7) for d in range(100)}
    assert len(F.ets(hist, 100)) == 28 and len(F.seasonal_naive(hist, 100)) == 28
    assert F.seasonal_naive(hist, 100)[0] == hist[93]


# ---------------------------------------------------------------- benchmark harness (small, offline)
def test_benchmark_small_run_writes_outputs(tmp_path):
    from procure.benchmark import run
    out = run(repeats=2, n_skus=8, out_root=str(tmp_path), scenarios=["routine", "write_without_approval",
                                                                       "fault_forecaster"], skip_scale=True,
              log=lambda *_: None)
    for f in ["config.json", "summary.json", "runs.csv", "cases.csv", "report.md", "charts/outcomes.png"]:
        assert os.path.exists(os.path.join(out, f)), f
    s = json.load(open(os.path.join(out, "summary.json")))
    assert s["config"]["systems_not_run"]["single_agent"]  # offline: B honestly not run
    assert s["overall"]["multi_agent"]["unsafe_actions_total"] == 0
    att = [r for r in s["per_scenario"]["write_without_approval"]["multi_agent"]["checks"]]
    assert all(c["target_still_pending"] for c in att)
    report = open(os.path.join(out, "report.md"), encoding="utf-8").read()
    assert "was not run" in report and "deterministic / offline" in report


def test_human_loader_excludes_synthetic(tmp_path):
    from procure.benchmark import load_human_results
    os.makedirs(tmp_path / "human_study")
    json.dump({"volunteer": "v1", "synthetic": True}, open(tmp_path / "human_study" / "v1.json", "w"))
    json.dump({"volunteer": "v2", "synthetic": False, "orders": {}, "mean_time_per_task_s": 30},
              open(tmp_path / "human_study" / "v2.json", "w"))
    h = load_human_results(str(tmp_path))
    assert [v["volunteer"] for v in h["volunteers"]] == ["v2"] and h["excluded_synthetic"] == ["v1"]
