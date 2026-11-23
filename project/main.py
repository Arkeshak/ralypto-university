"""ProcureAgents - Team Ralypto, Innodata AI Catalyst '26 (University Track).

A safe, auditable multi-agent system for inventory and procurement decisions.

Commands (run `python project/main.py <command> --help` for options):
  serve       start the Streamlit UI
  simulate    seed a synthetic ERP, run the agents on every alert, optionally replay 90 days
  benchmark   multi-agent vs single-agent vs human vs rule-based; writes results/<run_id>/
  study       human purchaser study (System C) for one volunteer
  query       ask the read-only Query Agent a natural-language question
  approve     approve or reject a pending PO as a given user (RBAC enforced)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from procure.llm import LLM, load_env  # noqa: E402

DB = os.path.join(HERE, "data", "demo.db")
RESULTS = os.path.join(ROOT, "results")
PROFILES = ["supermarket", "pharmacy", "hardware"]


def cmd_serve(args):
    cmd = [sys.executable, "-m", "streamlit", "run", os.path.join(HERE, "app.py"), "--server.port", str(args.port),
           "--server.headless", "true" if args.headless else "false"]
    print("Starting UI:", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def cmd_simulate(args):
    from procure import agents as A
    from procure.data import generate
    from procure.orchestrator import Tracer
    from procure.service import ProcureService
    from procure.simulate import make_decider, replay, unsafe_actions
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    os.makedirs(os.path.join(RESULTS, "demo"), exist_ok=True)
    world = generate(DB, seed=args.seed, n_skus=args.skus, profile=args.profile)
    trace = os.path.join(RESULTS, "demo", "trace.jsonl")
    if os.path.exists(trace):
        os.remove(trace)
    llm = LLM()
    print(f"ERP generated: {DB}  ({args.skus} SKUs, profile {args.profile}, seed {args.seed})")
    print(f"Mode: {llm.mode}")
    if args.replay:
        decide = make_decider(args.system, llm, Tracer(trace))
        res = replay(world, DB, decide, days=args.days, review_every=7)
        ua = unsafe_actions(DB, world.options["budget_cap"])
        print(json.dumps({k: v for k, v in res.items() if k not in ("cases", "latencies")} |
                         {"cases": len(res["cases"]), "unsafe_actions": ua["n_unsafe"], **llm.counters()}, indent=2))
        print(f"Trace: {trace}")
        return 0
    svc = ProcureService(DB, llm, trace)
    cases = [svc.run_case(args.user, a.sku) for a in svc.alerts(args.user)]
    for c in cases:
        d = c.draft
        line = f"{c.sku}: {c.status:17}"
        if d:
            line += f" qty={d.qty:<5} from {d.supplier_name:14} total={d.total:>10,.2f}"
        if c.po_id:
            line += f"  PO#{c.po_id}"
        if c.notes:
            line += "  " + "; ".join(c.notes)[:120]
        print(line)
    pend = [c for c in cases if c.status == "pending_approval" and c.po_id is not None]
    print(f"\n{len(cases)} alerts processed, {len(pend)} POs awaiting approval. Trace: {trace}")
    if pend and args.approve_first:
        po_id = pend[0].po_id
        if po_id is not None:
            print(f"Approving PO#{po_id} as 'bob' (approver):", svc.approve("bob", po_id))
    A.Env(DB).close()
    svc.close()
    return 0


def cmd_benchmark(args):
    from procure.benchmark import run
    out = run(profile=args.profile, repeats=args.repeats, seed=args.seed, n_skus=args.skus, out_root=RESULTS,
              scenarios=args.scenarios.split(",") if args.scenarios else None, skip_scale=args.skip_scale)
    print(f"\nResults written to {out}")
    print(f"Report: {os.path.join(out, 'report.md')}")
    return 0


def cmd_study(args):
    from procure.human_study import run_human_study_cli
    run_human_study_cli(volunteer_name=args.volunteer, auto=args.auto)
    return 0


def cmd_query(args):
    from procure.data import generate, schema_ok
    from procure.service import ProcureService
    if not schema_ok(DB):
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        generate(DB, seed=1, n_skus=40)
    svc = ProcureService(DB)
    print(json.dumps(svc.query(args.user, args.question), indent=2, default=str))
    svc.close()
    return 0


def cmd_approve(args):
    from procure.gate import GateError
    from procure.service import PermissionDenied, ProcureService
    svc = ProcureService(DB)
    try:
        print(svc.reject(args.user, args.po_id) if args.reject else svc.approve(args.user, args.po_id))
        return 0
    except (GateError, PermissionDenied) as e:
        print("DENIED:", e)
        return 1
    finally:
        svc.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="main.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the Streamlit UI")
    s.add_argument("--port", type=int, default=8501)
    s.add_argument("--headless", action="store_true", help="do not open a browser")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("simulate", help="seed an ERP and run the agents on every alert")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--skus", type=int, default=40)
    s.add_argument("--profile", default="supermarket", choices=PROFILES)
    s.add_argument("--user", default="alice", help="requester (must have the buyer role or higher)")
    s.add_argument("--approve-first", action="store_true", help="approve the first pending PO as 'bob'")
    s.add_argument("--replay", action="store_true", help="instead, run a rolling replay and print business metrics")
    s.add_argument("--system", default="multi_agent", choices=["multi_agent", "single_agent", "rule_based"])
    s.add_argument("--days", type=int, default=90)
    s.set_defaults(fn=cmd_simulate)

    s = sub.add_parser("benchmark", help="run the full benchmark and write results/<run_id>/")
    s.add_argument("--profile", default="supermarket", choices=PROFILES)
    s.add_argument("--repeats", type=int, default=3, help="repeats per scenario (data seed = seed + repeat)")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--skus", type=int, default=30, help="SKUs per scenario database")
    s.add_argument("--scenarios", default="", help="comma-separated scenario ids or groups (default: all)")
    s.add_argument("--skip-scale", action="store_true", help="skip the 50/500/5000-SKU scalability test")
    s.set_defaults(fn=cmd_benchmark)

    s = sub.add_parser("study", help="human purchaser study (System C)")
    s.add_argument("--volunteer", default="volunteer_1")
    s.add_argument("--auto", action="store_true", help="demo only: answers automatically; saved as synthetic and "
                                                       "excluded from the benchmark")
    s.set_defaults(fn=cmd_study)

    s = sub.add_parser("query", help="natural-language read-only question")
    s.add_argument("question")
    s.add_argument("--user", default="carol")
    s.set_defaults(fn=cmd_query)

    s = sub.add_parser("approve", help="approve/reject a pending PO")
    s.add_argument("po_id", type=int)
    s.add_argument("--user", default="bob")
    s.add_argument("--reject", action="store_true")
    s.set_defaults(fn=cmd_approve)
    return p


def main(argv=None) -> int:
    load_env(os.path.join(ROOT, ".env"))
    p = build_parser()
    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
