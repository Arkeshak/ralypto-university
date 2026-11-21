import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from procure import agents as A
from procure.data import generate
from procure.gate import Gate, GateError
from procure.orchestrator import Tracer, run_case
from procure.query import UnsafeQuery, ask, check_sql
from procure.models import DraftPO


@pytest.fixture
def world(tmp_path):
    p = str(tmp_path / "t.db")
    w = generate(p, 5, 25)
    return w, A.Env(p), Gate(p)


def first_alert(w, env):
    return next(s for s in w.truth if A.stock_monitor(env, s))


def test_same_seed_same_data(tmp_path):
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    generate(a, 9, 10); generate(b, 9, 10)
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
    sku = first_alert(w, env)
    c = run_case(env, gate, Tracer(None), sku)
    fc = c.forecast
    bad = c.draft.model_copy(update={"qty": 0, "unit_price": 0.01})
    v = A.validator(env, bad, fc, "alice")
    assert not v.passed and {"PRICE", "SANITY"} <= {f.code for f in v.failures}


def test_budget_blocks_and_escalates(tmp_path):
    p = str(tmp_path / "b.db")
    w = generate(p, 5, 25, budget_cap=100.0)
    env, gate = A.Env(p), Gate(p)
    cs = [run_case(env, gate, Tracer(None), s) for s in w.truth]
    assert gate.committed_spend() <= 100.0
    assert any(c.status == "escalated" for c in cs)


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
