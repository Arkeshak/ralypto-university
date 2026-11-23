"""System C: human purchaser study protocol (Proposal Sections 7.1 and 7.3).

A volunteer sees the same ERP information the agents see (stock, expiring batches,
30-day sales, supplier price lists) for 10 scenarios and types a supplier and a
quantity. Decisions and per-task time are saved to results/human_study/<volunteer>.json.
The benchmark re-scores these decisions with the same validator, gate and 21-day replay
it uses for systems A, B and D on the identical scenarios.

`--auto` exists only to demo the flow. Its file is marked "synthetic": true and the
benchmark never counts it as a human result.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import tempfile
import time
import uuid
from typing import Dict, List, Optional

from . import agents as A
from .data import generate, ro_connect
from .llm import LLM
from .models import CaseFile, DraftPO

STUDY_SEED, STUDY_SKUS, STUDY_PROFILE, STUDY_N = 42, 40, "supermarket", 10


def get_study_scenarios(db_path: str, n_scenarios: int = STUDY_N) -> List[Dict]:
    """The standard 10-scenario subset: the first n SKUs the Stock Monitor flags."""
    env = A.Env(db_path, use_lgbm=False)
    db = ro_connect(db_path)
    skus = [r["sku"] for r in db.execute("SELECT sku FROM items ORDER BY sku")]
    scenarios = []
    for sku in [s for s in skus if A.stock_monitor(env, s)][:n_scenarios]:
        item = db.execute("SELECT * FROM items WHERE sku=?", (sku,)).fetchone()
        stock = db.execute("SELECT on_hand FROM stock WHERE sku=?", (sku,)).fetchone()
        batches = db.execute("SELECT qty, expiry_day FROM batches WHERE sku=?", (sku,)).fetchall()
        suppliers = db.execute("SELECT p.supplier_id, s.name, p.unit_price, p.moq, p.lead_time_days, s.reliability "
                               "FROM prices p JOIN suppliers s ON s.id=p.supplier_id WHERE p.sku=? AND p.in_stock=1 "
                               "ORDER BY p.unit_price", (sku,)).fetchall()
        recent = [q for d, q in env.history(sku) if d >= env.today - 30 and q >= 0]
        scenarios.append({
            "idx": len(scenarios) + 1, "sku": sku, "name": item["name"], "category": item["category"],
            "unit_cost": item["unit_cost"], "shelf_life_days": item["shelf_life_days"],
            "reorder_point": item["reorder_point"], "on_hand": stock["on_hand"] if stock else 0,
            "expiring_batches": [dict(b) for b in batches if b["expiry_day"] and b["expiry_day"] <= env.today + 14],
            "sales_30d_total": sum(recent), "sales_30d_avg": round(sum(recent) / max(1, len(recent)), 2),
            "suppliers": [dict(s) for s in suppliers]})
    db.close()
    env.close()
    return scenarios


def score_orders(base_db: str, orders: Dict[str, tuple]) -> Dict:
    """Score a set of {sku: (supplier_id, qty)} decisions on the study scenarios.

    The orders go through the same validator and gate as every system, are approved by
    the same simulated approver, then replayed for 21 days against the true demand.
    """
    from .benchmark import po_accurate, reference_order
    from .simulate import replay
    work = tempfile.mkdtemp(prefix="procure_hs_")
    path = os.path.join(work, "s.db")
    world = generate(path, STUDY_SEED, STUDY_SKUS, STUDY_PROFILE)
    env0 = A.Env(path, use_lgbm=False)
    skus = [s["sku"] for s in get_study_scenarios(path)]
    refs = {s: reference_order(env0, world, s) for s in skus}
    env0.close()
    rejected = []

    def decide(env, gate, sku, rnd):
        case = CaseFile(task_id=uuid.uuid4().hex[:8], sku=sku, requester="alice")
        o = orders.get(sku)
        if not o or o[1] <= 0:
            case.status = "no_action"
            return case
        row = env.db.execute("SELECT p.unit_price, s.name FROM prices p JOIN suppliers s ON s.id=p.supplier_id "
                             "WHERE p.sku=? AND p.supplier_id=?", (sku, o[0])).fetchone()
        if not row:
            rejected.append(sku)
            case.status = "escalated"
            return case
        case.draft = DraftPO(sku=sku, supplier_id=o[0], supplier_name=row["name"], qty=int(o[1]),
                             unit_price=row["unit_price"])
        case.forecast = A.forecaster(env, sku)
        case.validation = A.validator(env, case.draft, case.forecast, "alice")
        if not case.validation.passed:
            rejected.append(sku)
            case.status = "escalated"
            return case
        case.po_id = gate.submit(case, f"{case.task_id}-{sku}")
        case.status = "pending_approval"
        return case
    decide.llm, decide.lgbm = LLM(provider="offline"), False
    res = replay(world, path, decide, days=21, review_every=21, skus=skus, single_round=True)
    acc = statistics.mean(po_accurate(refs[s], (orders[s][0], orders[s][1]) if s in orders and s not in rejected
                                      else None) for s in skus)
    shutil.rmtree(work, ignore_errors=True)
    return {"stockout_rate": res["stockout_rate"], "overstock_value": res["overstock_value"],
            "expiry_writeoff_value": res["expiry_writeoff_value"], "po_accuracy": acc,
            "orders_placed": len(orders), "orders_rejected_by_validator": len(rejected)}


def run_human_study_cli(volunteer_name: str = "volunteer_1", results_dir: Optional[str] = None,
                        auto: bool = False) -> Dict:
    """Interactive protocol. With auto=True a fixed demo policy answers and the file is marked synthetic."""
    from .service import results_root
    results_dir = results_dir or os.path.join(results_root(), "human_study")
    os.makedirs(results_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="procure_study_")
    db = os.path.join(work, "study.db")
    generate(db, STUDY_SEED, STUDY_SKUS, STUDY_PROFILE)
    scenarios = get_study_scenarios(db)
    print("=" * 64)
    print("  ProcureAgents - Human purchaser study (System C)")
    print(f"  Volunteer: {volunteer_name} | Scenarios: {len(scenarios)}" + ("  [SYNTHETIC DEMO MODE]" if auto else ""))
    print("  For each item choose a supplier id (0 = no order) and a quantity.")
    print("=" * 64)
    orders, times = {}, []
    for s in scenarios:
        print(f"\n--- Scenario {s['idx']}/{len(scenarios)}: {s['sku']} ({s['name']}) ---")
        print(f"Unit cost {s['unit_cost']:.2f} | shelf life {s['shelf_life_days'] or 'non-perishable'} | "
              f"on hand {s['on_hand']} | reorder point {s['reorder_point']}")
        print(f"Expiring within 14 days: {sum(b['qty'] for b in s['expiring_batches'])} units | "
              f"sales last 30 days: {s['sales_30d_total']} (avg {s['sales_30d_avg']}/day)")
        for sp in s["suppliers"]:
            print(f"  [{sp['supplier_id']}] {sp['name']:15} price {sp['unit_price']:7.2f}  MOQ {sp['moq']:3}  "
                  f"lead {sp['lead_time_days']:2}d  reliability {sp['reliability']:.0%}")
        t0 = time.perf_counter()
        if auto:  # demo policy: cheapest supplier, 21 days of average demand minus stock
            sp = s["suppliers"][0] if s["suppliers"] else None
            sid = sp["supplier_id"] if sp else 0
            qty = max(sp["moq"], math.ceil(21 * s["sales_30d_avg"] - s["on_hand"])) if sp else 0
            print(f"> auto decision: supplier {sid}, qty {qty}")
        else:
            try:
                sid = int(input("Supplier id (0 = no order): ").strip() or 0)
                qty = int(input("Quantity: ").strip() or 0) if sid else 0
            except (ValueError, EOFError):
                print("No valid input; recorded as no order.")
                sid, qty = 0, 0
        times.append(time.perf_counter() - t0)
        if sid and qty > 0:
            orders[s["sku"]] = (sid, qty)
    scores = score_orders(db, orders)
    result = {"system": "C. Human purchasers", "volunteer": volunteer_name, "synthetic": bool(auto),
              "date": time.strftime("%Y-%m-%d %H:%M:%S"), "study_seed": STUDY_SEED, "n_scenarios": len(scenarios),
              "orders": {k: list(v) for k, v in orders.items()},
              "task_times_s": [round(t, 2) for t in times],
              "mean_time_per_task_s": round(statistics.mean(times), 2) if times else None, **scores}
    out_file = os.path.join(results_dir, f"{volunteer_name}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print("\n---------------- RESULTS ----------------")
    print(f"Stockout rate (21-day replay): {result['stockout_rate']:.1%}")
    print(f"Expiry write-off value:        {result['expiry_writeoff_value']:,.2f}")
    print(f"Overstock value (avg/day):     {result['overstock_value']:,.2f}")
    print(f"PO accuracy vs reference:      {result['po_accuracy']:.0%}")
    print(f"Mean time per task:            {result['mean_time_per_task_s']} s")
    print(f"Saved to {out_file}" + ("  (synthetic: excluded from the benchmark)" if auto else ""))
    shutil.rmtree(work, ignore_errors=True)
    return result
