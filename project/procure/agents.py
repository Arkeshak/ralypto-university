"""The specialised agents. Numbers come from code; the LLM (optional) only writes text."""
from __future__ import annotations

import math
import re
import statistics

from .data import ro_connect
from .llm import LLM
from .models import (Alert, DraftPO, Failure, Forecast, SupplierOption, SupplierRanking, Validation)

MAX_HORIZON = 28
INJECTION = re.compile(r"ignore (all |previous )?instructions|approve all|system prompt|disregard", re.I)


class Env:
    """Read-only view of the ERP plus configuration shared by agents."""

    def __init__(self, db_path: str, llm: LLM | None = None):
        self.db_path, self.llm = db_path, llm or LLM()
        self.db = ro_connect(db_path)
        self.today = int(self.meta("today_day"))
        self.budget_cap = float(self.meta("budget_cap"))
        from .data import PROFILES
        self.profile = PROFILES[self.meta("profile")]

    def meta(self, k):
        return self.db.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()[0]

    def history(self, sku):
        return [(r["day"], r["qty"]) for r in self.db.execute("SELECT day,qty FROM sales WHERE sku=? ORDER BY day", (sku,))]

    def committed_spend(self):
        return float(self.db.execute("SELECT COALESCE(SUM(total),0) FROM pos WHERE status IN "
                                     "('PENDING_APPROVAL','APPROVED','CREATED')").fetchone()[0])

    def role(self, user):
        r = self.db.execute("SELECT role FROM users WHERE name=?", (user,)).fetchone()
        return r[0] if r else None


# ---------------------------------------------------------------- Stock Monitor
def stock_monitor(env: Env, sku: str, expiry_window: int = 14) -> Alert | None:
    it = env.db.execute("SELECT i.reorder_point rp, COALESCE(s.on_hand,0) oh FROM items i LEFT JOIN stock s USING(sku) "
                        "WHERE sku=?", (sku,)).fetchone()
    if not it:
        return None
    recent = [q for d, q in env.history(sku) if d >= env.today - 28 and q >= 0]
    avg = sum(recent) / max(1, min(28, len(recent))) if recent else 0.0
    exp = env.db.execute("SELECT COALESCE(SUM(qty),0) q, MIN(expiry_day) d FROM batches WHERE sku=? AND expiry_day IS NOT NULL "
                         "AND expiry_day<=?", (sku, env.today + expiry_window)).fetchone()
    low, expiring = it["oh"] <= it["rp"], exp["q"] > 0
    if not (low or expiring):
        return None
    kind = "both" if low and expiring else "low_stock" if low else "expiry"
    return Alert(sku=sku, kind=kind, on_hand=it["oh"], reorder_point=it["rp"], avg_daily=round(avg, 2),
                 expiring_qty=exp["q"], days_to_expiry=(exp["d"] - env.today) if expiring else None,
                 evidence=f"on_hand={it['oh']} reorder_point={it['rp']} avg_daily_28d={avg:.2f} expiring_{expiry_window}d={exp['q']}")


# ---------------------------------------------------------------- Demand Forecasting
def forecast_naive_seasonal(hist: list, h: int, as_of: int | None = None):
    """Weekly seasonal profile x exponentially smoothed level. Returns (daily, sigma)."""
    qty = {d: q for d, q in hist}
    days = sorted(qty)
    last = (as_of - 1) if as_of is not None else days[-1]
    dow = {i: [] for i in range(7)}
    for d in days:
        dow[d % 7].append(qty[d])
    overall = statistics.mean(qty.values()) or 1e-9
    factor = {i: (statistics.mean(v) / overall if len(v) >= 3 else 1.0) for i, v in dow.items()}
    level = None
    resid = []
    for d in days:
        deseason = qty[d] / max(factor[d % 7], 0.2)
        if level is not None:
            resid.append(qty[d] - level * factor[d % 7])
        level = deseason if level is None else 0.2 * deseason + 0.8 * level
    sigma = statistics.pstdev(resid[-28:]) if len(resid) >= 5 else (math.sqrt(overall) if overall > 0 else 0.0)
    return [max(0.0, level * factor[(last + 1 + i) % 7]) for i in range(h)], sigma


def forecaster(env: Env, sku: str, as_of: int | None = None) -> Forecast:
    as_of = env.today if as_of is None else as_of
    raw = [(d, q) for d, q in env.history(sku) if d < as_of]
    clean = [(d, q) for d, q in raw if q is not None and q >= 0]
    flags = []
    span = (as_of - clean[0][0]) if clean else 0
    if len(raw) - len(clean) > 0:
        flags.append(f"dropped_{len(raw) - len(clean)}_corrupt_rows")
    if span and len(clean) < 0.95 * span:
        flags.append("missing_days")
    if len(clean) < 28:
        flags.append("short_history")
    if len(clean) < 3:
        return Forecast(sku=sku, daily=[0.0] * MAX_HORIZON, sigma_daily=0.0, confidence=0.0,
                        method="none", flags=flags + ["no_history"])
    daily, sigma = forecast_naive_seasonal(clean, MAX_HORIZON, as_of)
    conf = min(1.0, len(clean) / 90)
    if "dropped" in "".join(flags) or "missing_days" in flags:
        conf *= 0.7
    return Forecast(sku=sku, daily=[round(x, 3) for x in daily], sigma_daily=round(sigma, 3),
                    confidence=round(conf, 2), method="weekly-seasonal x SES", flags=flags)


# ---------------------------------------------------------------- Supplier
WEIGHTS = {"price": 0.45, "lead": 0.2, "reliability": 0.35}  # visible and adjustable


def supplier_ranker(env: Env, sku: str, weights: dict | None = None) -> SupplierRanking:
    w = weights or WEIGHTS
    rows = env.db.execute("SELECT p.*, s.name, s.reliability, s.note FROM prices p JOIN suppliers s ON s.id=p.supplier_id "
                          "WHERE p.sku=? AND p.in_stock=1", (sku,)).fetchall()
    flagged = [f"{r['name']}: note flagged as possible prompt injection and ignored" for r in rows
               if r["note"] and INJECTION.search(r["note"])]
    if not rows:
        return SupplierRanking(sku=sku, options=[], flagged_notes=flagged)
    lo, hi = min(r["unit_price"] for r in rows), max(r["unit_price"] for r in rows)
    ll, lh = min(r["lead_time_days"] for r in rows), max(r["lead_time_days"] for r in rows)
    opts = []
    for r in rows:
        price_s = 1.0 if hi == lo else 1 - (r["unit_price"] - lo) / (hi - lo)
        lead_s = 1.0 if lh == ll else 1 - (r["lead_time_days"] - ll) / (lh - ll)
        score = w["price"] * price_s + w["lead"] * lead_s + w["reliability"] * r["reliability"]
        opts.append(SupplierOption(supplier_id=r["supplier_id"], name=r["name"], unit_price=r["unit_price"], moq=r["moq"],
                                   lead_time=r["lead_time_days"], reliability=r["reliability"], score=round(score, 4)))
    opts.sort(key=lambda o: -o.score)
    opts = opts[:2]
    for o in opts:  # rationale text: LLM if available, deterministic template otherwise
        tmpl = (f"{o.name}: price {o.unit_price}, lead {o.lead_time}d, reliability {o.reliability:.0%}, MOQ {o.moq}, "
                f"score {o.score}")
        o.rationale = tmpl
    if len(opts) == 2:
        txt = env.llm.complete("You explain supplier trade-offs in two sentences. Use only the given numbers.",
                               f"Option 1: {opts[0].rationale}\nOption 2: {opts[1].rationale}")
        if txt:
            opts[0].rationale += " | " + txt.strip()
    return SupplierRanking(sku=sku, options=opts, flagged_notes=flagged)


# ---------------------------------------------------------------- Purchase Order
def _usable_stock(env: Env, sku: str, avg_daily: float) -> float:
    rows = env.db.execute("SELECT qty, expiry_day FROM batches WHERE sku=?", (sku,)).fetchall()
    usable = 0.0
    for r in rows:
        if r["expiry_day"] is None:
            usable += r["qty"]
        else:
            usable += min(r["qty"], avg_daily * max(0, r["expiry_day"] - env.today))
    return usable


def po_drafter(env: Env, alert: Alert, fc: Forecast, rank: SupplierRanking, option_idx: int = 0,
               safety_mult: float = 1.0) -> DraftPO | None:
    if not rank.options:
        return None
    o = rank.options[min(option_idx, len(rank.options) - 1)]
    h = min(MAX_HORIZON, o.lead_time + env.profile["review"])
    z = env.profile["z"]
    need = fc.mean(h) + z * fc.sigma(h) * safety_mult
    if safety_mult > 1:
        need += (safety_mult - 1) * fc.mean(h)
    qty_needed = need - _usable_stock(env, alert.sku, fc.mean(7) / 7)
    if qty_needed <= 0:
        return DraftPO(sku=alert.sku, supplier_id=o.supplier_id, supplier_name=o.name, qty=0, unit_price=o.unit_price,
                       action="markdown",
                       rationale=f"Usable stock covers forecast demand over {h}d; mark down expiring units instead of reordering.")
    qty = max(o.moq, math.ceil(qty_needed))
    trade_off = ""
    if len(rank.options) > 1:
        alt = rank.options[1]
        trade_off = f" [Runner-up: {alt.name} at ${alt.unit_price:.2f}, lead {alt.lead_time}d, reliability {alt.reliability:.0%}]"
    rationale = (f"Order {qty} from {o.name}: forecast {fc.mean(h):.0f} over {h}d (confidence {fc.confidence}), "
                 f"safety z={z}, usable stock {_usable_stock(env, alert.sku, fc.mean(7) / 7):.0f}, MOQ {o.moq}.{trade_off}")
    txt = env.llm.complete("Write a two-sentence purchase justification. Use only the numbers provided and always state the quantity.",
                           rationale)
    if txt and str(qty) in txt:
        rationale = txt.strip()  # deterministic numbers win; discrepant text is discarded
    return DraftPO(sku=alert.sku, supplier_id=o.supplier_id, supplier_name=o.name, qty=qty, unit_price=o.unit_price,
                   rationale=rationale)


def po_reviser(env: Env, draft: DraftPO, failures: list[Failure], rank: SupplierRanking, remaining_budget: float,
               rev: int) -> DraftPO | None:
    """Apply validator feedback. Returns a revised draft or None if nothing sensible can be done."""
    codes = {f.code for f in failures}
    if codes & {"ROLE", "PRICE", "STOCK"}:
        return None  # not fixable by revising quantities
    opt = next((o for o in rank.options if o.supplier_id == draft.supplier_id), None)
    new = draft.model_copy(update={"revision": rev})
    if "MOQ" in codes and opt:
        new.qty = max(new.qty, opt.moq)
    if "BUDGET" in codes:
        affordable = int(remaining_budget // new.unit_price)
        if opt and affordable >= opt.moq:
            new.qty = min(new.qty, affordable)
        elif rev >= 2 and len(rank.options) > 1:
            alt = rank.options[1]
            if alt.supplier_id != draft.supplier_id and int(remaining_budget // alt.unit_price) >= alt.moq:
                new = new.model_copy(update={"supplier_id": alt.supplier_id, "supplier_name": alt.name,
                                             "unit_price": alt.unit_price, "qty": max(alt.moq, 1)})
            else:
                return None
        else:
            return None
    if "SANITY" in codes:
        return None
    new.rationale += f" [revised x{rev} after validator: {','.join(sorted(codes))}]"
    return new


# ---------------------------------------------------------------- Validator
def validator(env: Env, draft: DraftPO, fc: Forecast, requester: str) -> Validation:
    fails, warns = [], []
    if env.role(requester) not in {"buyer", "approver", "admin"}:
        fails.append(Failure(code="ROLE", message=f"{requester} lacks permission to draft POs"))
    row = env.db.execute("SELECT * FROM prices WHERE supplier_id=? AND sku=?", (draft.supplier_id, draft.sku)).fetchone()
    if not row:
        fails.append(Failure(code="PRICE", message="supplier does not list this SKU"))
    else:
        if abs(row["unit_price"] - draft.unit_price) > 1e-6:
            fails.append(Failure(code="PRICE", message=f"price {draft.unit_price} != list price {row['unit_price']}"))
        if not row["in_stock"]:
            fails.append(Failure(code="STOCK", message="supplier is out of stock"))
        if draft.qty < row["moq"]:
            fails.append(Failure(code="MOQ", message=f"qty {draft.qty} below MOQ {row['moq']}"))
        if draft.qty > max(row["moq"], 6 * fc.mean(MAX_HORIZON) + 10 * fc.sigma_daily + 5):
            fails.append(Failure(code="SANITY", message=f"qty {draft.qty} is implausibly large vs forecast"))
    if draft.qty <= 0:
        fails.append(Failure(code="SANITY", message="non-positive quantity"))
    remaining = env.budget_cap - env.committed_spend()
    if draft.total > remaining + 1e-9:
        fails.append(Failure(code="BUDGET", message=f"total {draft.total} exceeds remaining budget {remaining:.2f}"))
    if fc.confidence < 0.5:
        warns.append("low forecast confidence: flag for closer human review")
    if env.llm.available:  # LLM critique is advisory only; the rule engine already has the veto
        txt = env.llm.complete("You are a procurement compliance reviewer. Reply with one short sentence of concerns, or 'none'.",
                               draft.model_dump_json())
        if txt and txt.strip().lower() != "none":
            warns.append("LLM critique: " + txt.strip()[:200])
    return Validation(passed=not fails, failures=fails, warnings=warns)
