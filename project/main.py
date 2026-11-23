"""ProcureAgents - Ralypto, Innodata AI Catalyst '26.

Commands:
  python project/main.py demo        seed a synthetic ERP, run the agents, approve one PO, print trace
  python project/main.py bench       full evaluation; writes project/results/*.json
  python project/main.py ask "..."   natural-language read-only query on the demo ERP
  python project/main.py approve ID  approve/reject a pending PO (as an approver)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from procure import agents as A  # noqa: E402
from procure.data import generate  # noqa: E402
from procure.evaluate import forecast_quality, query_eval, run_benchmark, safety_suite, scale_test  # noqa: E402
from procure.gate import Gate, GateError  # noqa: E402
from procure.llm import LLM, load_env  # noqa: E402
from procure.orchestrator import Tracer, run_case  # noqa: E402
from procure.query import ask  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "demo.db")
RESULTS = os.path.join(HERE, "results")


def cmd_demo(args):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    os.makedirs(RESULTS, exist_ok=True)
    generate(DB, seed=args.seed, n_skus=args.skus, profile=args.profile)
    env, gate = A.Env(DB, LLM()), Gate(DB)
    trace = os.path.join(RESULTS, "demo_trace.jsonl")
    if os.path.exists(trace):
        os.remove(trace)
    tracer = Tracer(trace)
    skus = [r[0] for r in env.db.execute("SELECT sku FROM items ORDER BY sku")]
    cases = [run_case(env, gate, tracer, s) for s in skus]
    for c in cases:
        if c.status != "no_action":
            d = c.draft
            print(f"{c.sku}: {c.status:17} " + (f"qty={d.qty} from {d.supplier_name} total={d.total}" if d else "") +
                  (f"  PO#{c.po_id}" if c.po_id else "") + (f"  {c.notes}" if c.notes else ""))
    pend = [c for c in cases if c.status == "pending_approval"]
    print(f"\n{len(pend)} POs awaiting approval. Trace: {trace}")
    if pend:
        print("Demo approval by user 'bob' (approver):", gate.decide(pend[0].po_id, "bob", True))
    env.db.close()
    gate.close()


def cmd_ask(args):
    if not os.path.exists(DB):
        cmd_demo(argparse.Namespace(seed=1, skus=40, profile="supermarket"))
    env = A.Env(DB, LLM())
    print(json.dumps(ask(env, args.question), indent=2, default=str))
    env.db.close()


def cmd_approve(args):
    gate = Gate(DB)
    try:
        print(gate.decide(args.po_id, args.user, not args.reject))
    except GateError as e:
        print("DENIED:", e)
    finally:
        gate.close()


def cmd_bench(args):
    os.makedirs(RESULTS, exist_ok=True)
    out = run_benchmark(RESULTS, seeds=tuple(range(1, args.seeds + 1)), n_skus=args.skus, profile=args.profile)
    extra = {"forecast_wape": forecast_quality(), "safety": safety_suite(), "queries": query_eval(),
             "scalability": scale_test()}
    json.dump(extra, open(os.path.join(RESULTS, "extra.json"), "w"), indent=2, default=str)
    print(json.dumps(out["summary"], indent=2))
    print(json.dumps({k: v for k, v in extra.items() if k != "queries"}, indent=2, default=str))
    print("queries:", {k: v for k, v in extra["queries"].items() if k != "details"})


def cmd_study(args):
    from procure.human_study import run_human_study_cli
    auto = None
    if args.auto:
        auto = [{"qty": 50, "time_s": 8.5}] * 10
    run_human_study_cli(volunteer_name=args.volunteer, auto_decisions=auto)


def main():
    load_env(os.path.join(HERE, "..", ".env"))
    p = argparse.ArgumentParser(description="ProcureAgents")
    sub = p.add_subparsers(dest="cmd")
    d = sub.add_parser("demo")
    d.add_argument("--seed", type=int, default=1)
    d.add_argument("--skus", type=int, default=40)
    d.add_argument("--profile", default="supermarket", choices=["supermarket", "pharmacy", "hardware"])
    q = sub.add_parser("ask")
    q.add_argument("question")
    a = sub.add_parser("approve")
    a.add_argument("po_id", type=int)
    a.add_argument("--user", default="bob")
    a.add_argument("--reject", action="store_true")
    b = sub.add_parser("bench")
    b.add_argument("--seeds", type=int, default=5)
    b.add_argument("--skus", type=int, default=40)
    b.add_argument("--profile", default="supermarket", choices=["supermarket", "pharmacy", "hardware"])
    s = sub.add_parser("study")
    s.add_argument("--volunteer", default="volunteer_1")
    s.add_argument("--auto", action="store_true")
    args = p.parse_args()
    {"demo": cmd_demo, "ask": cmd_ask, "approve": cmd_approve, "bench": cmd_bench, "study": cmd_study}.get(
        args.cmd, lambda _: p.print_help()
    )(args)


if __name__ == "__main__":
    main()
