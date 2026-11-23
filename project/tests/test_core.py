import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from procure import agents as A  # noqa: E402
from procure.data import generate  # noqa: E402
from procure.gate import Gate, GateError  # noqa: E402
from procure.orchestrator import Tracer, run_case  # noqa: E402
from procure.query import UnsafeQuery, ask, check_sql  # noqa: E402


@pytest.fixture
def world(tmp_path):
    p = str(tmp_path / "t.db")
    w = generate(p, 5, 25)
    env, gate = A.Env(p), Gate(p)
    yield w, env, gate
    env.close()
    gate.close()


def first_alert(w, env):
    return next(s for s in w.truth if A.stock_monitor(env, s))


def test_same_seed_same_data(tmp_path):
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    generate(a, 9, 10)
    generate(b, 9, 10)
    assert open(a, "rb").read() == open(b, "rb").read()


def test_case_ends_pending_and_only_approver_can_create(world):
    w, env, gate = world
    c = run_case(env, gate, Tracer(None), first_alert(w, env))
    assert c.status == "pending_approval" and c.po_id
    with pytest.raises(GateError):
        gate.decide(c.po_id, "alice", True)  # buyer
    assert gate.decide(c.po_id, "bob", True) == "CREATED"


def test_validator_vetoes_bad_moq_and_price(world):
    w, env, gate = world
    c = run_case(env, gate, Tracer(None), first_alert(w, env))
    bad = c.draft.model_copy(update={"qty": 0, "unit_price": 0.01})
    v = A.validator(env, bad, c.forecast, "alice")
    assert not v.passed and {"PRICE", "SANITY"} <= {f.code for f in v.failures}


def test_budget_blocks_and_escalates(tmp_path):
    p = str(tmp_path / "b.db")
    w = generate(p, 5, 25, budget_cap=100.0)
    env, gate = A.Env(p), Gate(p)
    cs = [run_case(env, gate, Tracer(None), s) for s in w.truth]
    assert gate.committed_spend() <= 100.0
    assert any(c.status == "escalated" for c in cs)
    env.close()
    gate.close()


def test_idempotent_submit(world):
    w, env, gate = world
    c = run_case(env, gate, Tracer(None), first_alert(w, env))
    assert gate.submit(c, f"{c.task_id}-{c.sku}") == c.po_id


def test_query_safety(world):
    w, env, gate = world
    assert ask(env, "Delete all sales")["status"] == "blocked"
    for bad in ["DROP TABLE items", "SELECT 1; SELECT 2", "SELECT * FROM users"]:
        with pytest.raises(UnsafeQuery):
            check_sql(bad)
    assert ask(env, "How many items do we stock?")["rows"] == [(25,)]


def test_audit_append_only(world):
    w, env, gate = world
    run_case(env, gate, Tracer(None), first_alert(w, env))
    with pytest.raises(Exception):
        gate.db.execute("UPDATE audit SET actor='x'")
    with pytest.raises(Exception):
        gate.db.execute("DELETE FROM audit")


def test_plug_in_registry(world):
    from procure.registry import default_registry
    w, env, gate = world
    sku = first_alert(w, env)
    custom = default_registry.copy()
    called = []

    def my_forecaster(env, s, as_of=None):
        called.append(s)
        return A.forecaster(env, s, as_of)
    custom.register("forecaster", my_forecaster)
    case = run_case(env, gate, Tracer(None), sku, registry=custom)
    assert sku in called and case.forecast is not None


def test_runner_up_trade_off_in_po(world):
    w, env, gate = world
    c = run_case(env, gate, Tracer(None), first_alert(w, env))
    if c.draft and len(c.ranking.options) > 1:
        assert "Runner-up" in c.draft.rationale


def test_business_profiles(tmp_path):
    for prof in ["supermarket", "pharmacy", "hardware"]:
        p = str(tmp_path / f"{prof}.db")
        generate(p, seed=1, n_skus=15, profile=prof)
        env = A.Env(p)
        assert env.meta("profile") == prof and env.profile["review"] in (7, 14)
        env.close()


def test_human_study_scenarios(world):
    from procure.human_study import get_study_scenarios
    _, env, _ = world
    scenarios = get_study_scenarios(env.db_path, n_scenarios=5)
    assert len(scenarios) == 5
    assert {"sku", "suppliers", "sales_30d_avg"} <= set(scenarios[0])
