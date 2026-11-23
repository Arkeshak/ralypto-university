"""System C: Human purchaser comparison protocol (Proposal Section 7.1 & 7.3).

Allows human volunteers to review 10 replenishment scenarios, make purchasing
decisions, record time and output, and benchmark their results against
Multi-agent (System A) and Rule-based (System D).
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Dict, List, Optional

from . import agents as A
from .data import generate, ro_connect
from .evaluate import reference_order, po_accurate, replay
from .gate import Gate


def get_study_scenarios(db_path: str, n_scenarios: int = 10, seed: int = 42) -> List[Dict]:
    """Generate or retrieve a standardized 10-scenario subset for human evaluation."""
    db = ro_connect(db_path)
    env = A.Env(db_path)
    skus = [r["sku"] for r in db.execute("SELECT sku FROM items ORDER BY sku")]
    
    alert_skus = [s for s in skus if A.stock_monitor(env, s)]
    selected_skus = alert_skus[:n_scenarios]
    
    scenarios = []
    for idx, sku in enumerate(selected_skus, 1):
        item = db.execute("SELECT * FROM items WHERE sku=?", (sku,)).fetchone()
        stock = db.execute("SELECT on_hand FROM stock WHERE sku=?", (sku,)).fetchone()
        batches = db.execute("SELECT qty, expiry_day FROM batches WHERE sku=?", (sku,)).fetchall()
        suppliers = db.execute(
            "SELECT p.supplier_id, s.name, p.unit_price, p.moq, p.lead_time_days, s.reliability "
            "FROM prices p JOIN suppliers s ON s.id=p.supplier_id "
            "WHERE p.sku=? AND p.in_stock=1 ORDER BY p.unit_price", (sku,)
        ).fetchall()
        
        hist = env.history(sku)
        recent = [q for d, q in hist if d >= env.today - 30]
        avg_daily = sum(recent) / max(1, len(recent)) if recent else 0.0
        
        scenarios.append({
            "idx": idx,
            "sku": sku,
            "name": item["name"],
            "category": item["category"],
            "unit_cost": item["unit_cost"],
            "shelf_life_days": item["shelf_life_days"],
            "reorder_point": item["reorder_point"],
            "on_hand": stock["on_hand"] if stock else 0,
            "expiring_batches": [dict(b) for b in batches if b["expiry_day"] and b["expiry_day"] <= env.today + 14],
            "sales_30d_total": sum(recent),
            "sales_30d_avg": round(avg_daily, 2),
            "suppliers": [dict(s) for s in suppliers],
        })
    db.close()
    return scenarios


def run_human_study_cli(
    volunteer_name: str = "volunteer_1",
    db_path: Optional[str] = None,
    results_dir: str = "project/results",
    auto_decisions: Optional[List[Dict]] = None,
) -> Dict:
    """Run an interactive or automated human study protocol."""
    os.makedirs(results_dir, exist_ok=True)
    temp_db = db_path or os.path.join(results_dir, "_work", "human_study.db")
    os.makedirs(os.path.dirname(temp_db), exist_ok=True)
    
    world = generate(temp_db, seed=42, n_skus=40, profile="supermarket")
    env = A.Env(temp_db)
    scenarios = get_study_scenarios(temp_db, n_scenarios=10)
    
    print(f"\n=======================================================")
    print(f"  Ralypto · Human Purchaser Evaluation (System C)")
    print(f"  Volunteer: {volunteer_name} | Scenarios: {len(scenarios)}")
    print(f"=======================================================\n")
    
    human_orders = {}
    task_times = []
    
    for s in scenarios:
        sku = s["sku"]
        print(f"--- Scenario {s['idx']}/{len(scenarios)}: {sku} ({s['name']}) ---")
        print(f"Category: {s['category']} | Unit Cost: ${s['unit_cost']:.2f} | Shelf Life: {s['shelf_life_days'] or 'Non-perishable'} days")
        print(f"Current Stock: {s['on_hand']} units | Reorder Point: {s['reorder_point']} units")
        print(f"Expiring within 14d: {sum(b['qty'] for b in s['expiring_batches'])} units")
        print(f"Sales last 30d: {s['sales_30d_total']} units (avg: {s['sales_30d_avg']} units/day)")
        print("\nAvailable Suppliers:")
        for sp in s["suppliers"]:
            print(f"  [{sp['supplier_id']}] {sp['name']:15} Price: ${sp['unit_price']:6.2f} | MOQ: {sp['moq']:3} | Lead: {sp['lead_time_days']:2}d | Rel: {sp['reliability']:.0%}")
        
        t0 = time.perf_counter()
        if auto_decisions and s['idx'] <= len(auto_decisions):
            # Automated / demo mode decision
            dec = auto_decisions[s['idx'] - 1]
            avail_sids = [sp["supplier_id"] for sp in s["suppliers"]]
            chosen_sid = dec.get("supplier_id")
            sid = chosen_sid if chosen_sid in avail_sids else (avail_sids[0] if avail_sids else 0)
            target_sp = next((sp for sp in s["suppliers"] if sp["supplier_id"] == sid), None)
            base_qty = dec.get("qty", 50)
            qty = max(target_sp["moq"], base_qty) if target_sp else 0
            elapsed = dec.get("time_s", 12.5)
            sp_name = target_sp["name"] if target_sp else "None"
            print(f"> Decision (auto): Supplier {sid} ({sp_name}), Qty {qty} (took {elapsed:.1f}s)")
        else:
            try:
                sid_input = input("\nSelect Supplier ID (or 0 for no order): ").strip()
                sid = int(sid_input) if sid_input else 0
                if sid > 0:
                    qty_input = input("Enter Order Quantity: ").strip()
                    qty = int(qty_input) if qty_input else 0
                else:
                    qty = 0
            except (ValueError, EOFError):
                # Fallback if non-interactive
                sid = s["suppliers"][0]["supplier_id"] if s["suppliers"] else 0
                qty = max(s["suppliers"][0]["moq"], int(s["reorder_point"] - s["on_hand"])) if s["suppliers"] else 0
            elapsed = time.perf_counter() - t0
        
        task_times.append(elapsed)
        if sid > 0 and qty > 0:
            supplier = next((x for x in s["suppliers"] if x["supplier_id"] == sid), None)
            u_price = supplier["unit_price"] if supplier else 0.0
            human_orders[sku] = (sid, qty, u_price)
        print()
    
    # Evaluation replay against ground-truth world
    skus_evaluated = [s["sku"] for s in scenarios]
    replay_metrics = replay(world, temp_db, skus_evaluated, human_orders)
    
    # Oracle comparison
    refs = {s: reference_order(env, world, s) for s in skus_evaluated}
    acc = sum(po_accurate(refs[s], human_orders.get(s)) for s in skus_evaluated) / len(skus_evaluated)
    
    result = {
        "system": "System C (Human purchasers)",
        "volunteer": volunteer_name,
        "n_scenarios": len(scenarios),
        "unmet_rate": replay_metrics["unmet_rate"],
        "overstock_value": replay_metrics["overstock_value"],
        "expiry_writeoff_value": replay_metrics["expiry_writeoff_value"],
        "po_accuracy": acc,
        "mean_time_per_task_s": round(sum(task_times) / max(1, len(task_times)), 2),
        "total_time_s": round(sum(task_times), 2),
        "orders_placed": len(human_orders),
    }
    
    out_file = os.path.join(results_dir, f"human_study_{volunteer_name}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    print("\n---------------- RESULTS ----------------")
    print(f"Unmet Demand Rate:       {result['unmet_rate']:.1%}")
    print(f"Expiry Write-Off Value:  ${result['expiry_writeoff_value']:,.2f}")
    print(f"Overstock Value:         ${result['overstock_value']:,.2f}")
    print(f"PO Accuracy vs Oracle:   {result['po_accuracy']:.1%}")
    print(f"Average Time per Task:   {result['mean_time_per_task_s']}s")
    print(f"Saved to: {out_file}\n")
    
    env.db.close()
    return result
