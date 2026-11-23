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
