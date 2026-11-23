import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from procure import agents as A  # noqa: E402
from procure.data import generate  # noqa: E402
from procure.gate import Gate  # noqa: E402
from procure.orchestrator import Tracer, run_case  # noqa: E402
from procure.registry import default_registry  # noqa: E402


def test_supplier_risk(tmp_path):
    from procure.plugins.supplier_risk import supplier_risk
    reg = default_registry.copy()
    reg.register_extension("supplier_risk", supplier_risk)
    p = str(tmp_path / "x.db")
    w = generate(p, 1, 30)
    env, gate = A.Env(p), Gate(p)
    cases = [run_case(env, gate, Tracer(None), s, registry=reg) for s in w.truth]
    assert any("supplier_risk" in x for c in cases for v in c.validations for x in v.warnings)
    default_registry.unregister("supplier_risk")  # the import registered it globally; keep other tests clean
