# Extending ProcureAgents (Phase 2 readiness)

New agents and tools plug in through `project/procure/registry.py`. The orchestrator, gate and UI do not
change. Budget about 30 minutes for each of the recipes below, tests included.

## What you can plug in

| Extension point | How | Effect |
|---|---|---|
| Replace a core agent | `registry.register("forecaster", fn)` | The graph calls `fn` instead of the built-in agent (same signature) |
| Add a new checking agent | `registry.register_extension(name, fn, stage="validator")` | Runs after the Validator on every draft. Failures **veto** the PO; warnings appear on the approval card |
| Add a tool | `default_tool_registry.register(name, fn)` | Callable by any agent or extension via `default_tool_registry.call(name, ...)`; listed on the Settings page |
| New business profile | add an entry to `PROFILES` in `procure/data.py` | `--profile <name>` in every command |
| New benchmark scenario | add a `Scenario(...)` to `SCENARIOS` in `procure/benchmark.py` | Runs for every system with repeats, CIs and paired comparison |

Core agent signatures (see `procure/agents.py`):

```text
stock_monitor(env, sku) -> Alert | None
forecaster(env, sku, as_of=None) -> Forecast
supplier_ranker(env, sku, weights=None) -> SupplierRanking
po_drafter(env, alert, forecast, ranking, option_idx=0, safety_mult=1.0) -> DraftPO | None
po_reviser(env, draft, failures, ranking, remaining_budget, rev) -> DraftPO | None
validator(env, draft, forecast, requester) -> Validation
extension(env, draft, forecast, requester) -> Validation | None        # stage="validator"
```

`env.db` is a **read-only** connection (mode=ro, `PRAGMA query_only` and an SQLite authorizer). An agent
cannot write even if it tries; the only write path is `gate.Gate`.

## Worked example: a "Supplier risk" agent and an "FX rate" tool

Scenario: on Phase 2 day, Innodata asks for "do not concentrate more than 40% of open spend on one supplier,
and show the order value in USD".

Create `project/procure/plugins/supplier_risk.py`:

```python
"""Supplier concentration agent: vetoes a PO that would put > 40% of committed spend on one supplier."""
from procure.models import Failure, Validation
from procure.registry import default_registry, default_tool_registry

MAX_SHARE = 0.40


def fx_rate(currency: str = "USD") -> float:
    """Fixed demo FX rate from the ERP currency to `currency` (replace with a real read-only feed)."""
    return {"USD": 0.0033, "EUR": 0.0031}.get(currency, 1.0)


def supplier_risk(env, draft, forecast, requester):
    """Concentration check: share of committed spend per supplier after this PO."""
    rows = env.db.execute("SELECT supplier_id, SUM(total) FROM pos WHERE status IN "
                          "('PENDING_APPROVAL','APPROVED','CREATED') GROUP BY supplier_id").fetchall()
    spend = {sid: tot for sid, tot in rows}
    spend[draft.supplier_id] = spend.get(draft.supplier_id, 0.0) + draft.total
    total = sum(spend.values())
    share = spend[draft.supplier_id] / total if total else 0.0
    usd = draft.total * default_tool_registry.call("fx_rate", "USD")
    warn = [f"order value approx USD {usd:,.2f}; {draft.supplier_name} share after PO {share:.0%}"]
    if total > 5000 and share > MAX_SHARE:
        return Validation(passed=False, warnings=warn,
                          failures=[Failure(code="CONCENTRATION",
                                            message=f"{draft.supplier_name} would hold {share:.0%} of spend")])
    return Validation(passed=True, warnings=warn)


default_tool_registry.register("fx_rate", fx_rate)
default_registry.register_extension("supplier_risk", supplier_risk, stage="validator")
```

Activate it by importing the module once at start-up, for example at the end of
`procure/registry.py` (or at the top of `app.py` / `main.py`):

```python
import procure.plugins.supplier_risk  # noqa: F401  (registers the agent and the tool)
```

That is all. What happens now:

* The agent runs on every draft right after the Validator. A `CONCENTRATION` failure vetoes the PO,
  the PO agent gets the reasons, and after 2 revisions the case escalates to a human, exactly like a
  built-in rule.
* Its warnings (the USD value) show in the validator section of the approval card and in the trace.
* The Settings page lists `supplier_risk (extension @ validator)` and the `fx_rate` tool.
* The benchmark picks it up automatically, so its effect on stockouts and cost is measured.

Test it (`project/tests/test_plugin_example.py`):

```python
from procure import agents as A
from procure.data import generate
from procure.gate import Gate
from procure.orchestrator import Tracer, run_case
from procure.registry import default_registry


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
```

Use `default_registry.copy()` in tests and benchmark variants so the global registry stays clean.

## Adding a new graph node (bigger changes)

If a feature needs its own step in the workflow (not just a check), add a node in `build_graph()` in
`procure/orchestrator.py`:

1. Write `def n_my_step(state, config)` that returns a dict of state updates and a `trace` message
   (copy `n_supplier` as a template; `_msg(...)` builds the structured message).
2. `g.add_node("my_step", n_my_step)` and wire edges. To run it in parallel with Forecasting and Supplier,
   return it from `r_after_monitor` and add it to the join: `g.add_edge(["forecaster", "supplier", "my_step"], "po_agent")`.
3. Add any new state keys to the `State` TypedDict (lists need an `operator.add` reducer if parallel nodes write them).
4. Add a label in `AGENT_LABEL` in `project/ui/pages_ops.py` so the timeline names it.

## Checklist

- [ ] Agent reads only through `env.db` and never imports `sqlite3` to open its own write connection
- [ ] Numbers come from code; LLM text, if any, goes through `numbers_not_in()` (see `po_drafter`)
- [ ] Unit test added; `python -m pytest -q` and `python -m ruff check project` pass
- [ ] Registered name and docstring make sense on the Settings page
- [ ] If it changes outcomes, re-run `python project/main.py benchmark` and report the result honestly
