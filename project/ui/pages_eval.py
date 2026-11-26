"""Benchmark results and Settings / registry pages."""
from __future__ import annotations

import os

import altair as alt
import pandas as pd
import streamlit as st

from procure.agents import DEFAULT_WEIGHTS
from procure.orchestrator import LOW_CONFIDENCE, MAX_REVISIONS, SAFETY_BUFFER, mermaid
from procure.report import LABEL
from procure.service import PermissionDenied, load_run, results_root

from . import state
from . import theme as T

SYS_COLOR = {"multi_agent": T.PRIMARY, "single_agent": T.AMBER, "rule_based": T.GREY, "human": T.GREEN}


def _runs() -> dict:
    """Benchmark runs in results/ (local) and samples/benchmark/ (committed), newest first: name -> path."""
    roots = [results_root(), os.path.join(os.path.dirname(results_root()), "samples", "benchmark")]
    found = {}
    for root in roots:
        if os.path.isdir(root):
            for d in os.listdir(root):
                if os.path.exists(os.path.join(root, d, "summary.json")):
                    found.setdefault(d, os.path.join(root, d))
    return dict(sorted(found.items(), reverse=True))


def _ci_frame(ov: dict, systems: list, metric: str) -> pd.DataFrame:
    rows = []
    for s in systems:
        v = ov[s][metric]
        lo, hi = v["ci95"]
        rows.append({"system": LABEL[s], "key": s, "mean": v["mean"], "lo": lo if lo is not None else v["mean"],
                     "hi": hi if hi is not None else v["mean"]})
    return pd.DataFrame(rows)


def _ci_chart(df: pd.DataFrame, title: str):
    base = alt.Chart(df).encode(x=alt.X("system:N", title=None, sort=None))
    bars = base.mark_bar(size=38).encode(y=alt.Y("mean:Q", title=title),
                                         color=alt.Color("key:N", legend=None,
                                                         scale=alt.Scale(domain=list(SYS_COLOR),
                                                                         range=list(SYS_COLOR.values()))),
                                         tooltip=["system", "mean", "lo", "hi"])
    err = base.mark_errorbar(color=T.TEXT).encode(y="lo:Q", y2="hi:Q")
    return (bars + err).properties(height=230, title=title)


def benchmark():
    T.header(
        "Empirical Evaluation",
        "System Benchmark & ROI Analysis",
        "Comparative evaluation across rolling replay scenarios based on Proposal Section 7: "
        "System A (Multi-Agent MAS) vs System B (Single-Agent) vs System C (Human Baseline) vs System D (Rule-Based Floor)."
    )
    runs = _runs()
    if not runs:
        T.empty("No benchmark run found. Run:  python project/main.py benchmark --profile supermarket --repeats 3 --seed 1")
        return
    run = st.selectbox("Select Evaluation Experiment Run", list(runs))
    path = runs[run]
    s = load_run(path)
    cfg, ov = s["config"], s["overall"]
    systems = cfg["systems_run"]
    if "llm" not in cfg["llm_mode"]:
        T.callout(
            "**Offline Evaluation Benchmark (Proposal Section 7):** Deterministic scenario replay comparing "
            "System A (Collaborative Multi-Agent Architecture) against System C (Human Study) and "
            "System D (Rule-Based Static Baseline).",
            kind="info"
        )
    for sname, why in cfg.get("systems_not_run", {}).items():
        st.caption(f"{LABEL[sname]} not run: {why}")
    tabs = st.tabs(["Inventory Outcomes", "Safety & Compliance", "Cost & Latency", "Paired Comparison", "Scenario Drill-Down",
                    "Supplier Fairness", "Human Study", "Forecast & Queries", "Run Config"])
    with tabs[0]:
        c = st.columns(2)
        for i, m in enumerate(["stockout_rate", "overstock_value", "expiry_writeoff_value", "po_accuracy"]):
            c[i % 2].altair_chart(_ci_chart(_ci_frame(ov, systems, m), m.replace("_", " ")), use_container_width=True)
        st.caption("Replay scenarios, 90-day rolling replay. Bars: mean; whiskers: 95% bootstrap CI over "
                   "scenario x repeat runs.")
    with tabs[1]:
        df = pd.DataFrame([{"system": LABEL[x], "unsafe actions": ov[x]["unsafe_actions_total"],
                            "unsafe-action rate": ov[x]["unsafe_action_rate"], "POs submitted": ov[x]["n_pos_total"],
                            "validator catches": ov[x]["validator_catches_total"],
                            "fault success": ov[x]["fault_success_rate"]["mean"],
                            "fallback recovery": ov[x]["fallback_recovery_rate"]["mean"]} for x in systems])
        st.dataframe(df, hide_index=True, use_container_width=True)
        tot = sum(ov[x]["unsafe_actions_total"] for x in systems)
        (st.success if tot == 0 else st.error)(f"Unsafe actions across all systems and scenarios: {tot} (target 0).")
    with tabs[2]:
        c = st.columns(3)
        for i, m in enumerate(["latency_p50_s", "latency_p95_s", "cost_per_case_usd"]):
            c[i].altair_chart(_ci_chart(_ci_frame(ov, systems, m), m), use_container_width=True)
        st.dataframe(pd.DataFrame([{"system": LABEL[x], "tokens total": ov[x]["tokens_total"],
                                    "USD total": ov[x]["cost_usd_total"]} for x in systems]), hide_index=True)
        sc = s.get("scalability") or {}
        if sc:
            st.markdown("**Scalability (System A)**")
            st.dataframe(pd.DataFrame(sc.values()), hide_index=True, use_container_width=True)
    with tabs[3]:
        rows = []
        for k, v in s["paired"].items():
            pair, m = k.split(":")
            rows.append({"comparison": pair.replace("_minus_", " - "), "metric": m, "mean diff": v["mean_diff"],
                         "CI low": v["ci95"][0], "CI high": v["ci95"][1], "pairs": v["n_pairs"],
                         "first better": v["a_better"], "second better": v["b_better"], "ties": v["ties"]})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            T.empty("No paired comparisons in this run.")
        st.caption("A confidence interval that spans 0 means the run does not show a difference.")
        if os.path.exists(os.path.join(path, "charts", "paired.png")):
            st.image(os.path.join(path, "charts", "paired.png"))
    with tabs[4]:
        sc_id = st.selectbox("Scenario", list(s["per_scenario"]))
        desc = next((x for x in cfg["scenarios"] if x["id"] == sc_id), {})
        st.caption(f"{desc.get('group')} - {desc.get('description')} - kind {desc.get('kind')}")
        rows = []
        for x, r in s["per_scenario"][sc_id].items():
            rows.append({"system": LABEL[x], **{m: r[m]["mean"] for m in
                                                ["stockout_rate", "overstock_value", "expiry_writeoff_value",
                                                 "po_accuracy", "unsafe_actions", "success_rate", "escalation_rate",
                                                 "fallback_rate", "validator_catches", "latency_p50_s"]}})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        for x, r in s["per_scenario"][sc_id].items():
            checks = [{k: v for k, v in ch.items() if k != "unsafe_issues"} for ch in r["checks"]]
            if any(checks):
                st.markdown(f"**{LABEL[x]} checks per repeat**")
                st.json(checks, expanded=False)
        cases = os.path.join(path, "cases.csv")
        if os.path.exists(cases):
            df = pd.read_csv(cases)
            st.dataframe(df[df["scenario"] == sc_id].head(300), hide_index=True, use_container_width=True, height=280)
    with tabs[5]:
        names = {"1": "FastCheap Ltd", "2": "SteadySupply", "3": "MidTier Co", "4": "LocalSmall", "5": "GlobalBulk"}
        rows = [{"system": LABEL[x], "supplier": names.get(k, k), "share": v}
                for x in systems for k, v in ov[x]["supplier_share"].items()]
        if rows:
            ch = alt.Chart(pd.DataFrame(rows)).mark_bar().encode(
                x=alt.X("supplier:N", title=None), xOffset="system:N", y=alt.Y("share:Q", title="share of POs"),
                color=alt.Color("system:N", scale=alt.Scale(range=[SYS_COLOR[x] for x in systems])),
                tooltip=["system", "supplier", "share"])
            st.altair_chart(ch.properties(height=300), use_container_width=True)
        st.caption("How often each supplier receives the order. LocalSmall is the small local supplier the proposal "
                   "commits to monitoring for unfair disadvantage. Weights are visible and adjustable in Settings.")
    with tabs[6]:
        h = s["human"]
        if h["n_volunteers"] == 0:
            st.info("No human study results in this run. Each volunteer runs  python project/main.py study --volunteer "
                    "<name>  and the benchmark is re-run." + (f" Excluded synthetic files: {h['excluded_synthetic']}"
                                                             if h["excluded_synthetic"] else ""))
        rows = []
        for x, r in h["subset"]["results"].items():
            for y in (r if isinstance(r, list) else [r]):
                rows.append({"system": LABEL.get(x, x) + (f" ({y['volunteer']})" if "volunteer" in y else ""),
                             **{k: y.get(k) for k in ["stockout_rate", "overstock_value", "expiry_writeoff_value",
                                                      "po_accuracy", "mean_time_per_task_s"]}})
        st.markdown("Same 10 scenarios for every system (seed 42), single decision, 21-day replay.")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    with tabs[7]:
        fq = s["forecast"]["pooled"]
        st.markdown("**Forecast quality, 28-day hold-out**")
        st.dataframe(pd.DataFrame([{"model": m, **v} for m, v in sorted(fq.items(), key=lambda x: x[1]["wape"])]),
                     hide_index=True)
        q = s["queries"]
        st.markdown("**Natural-language queries**")
        st.dataframe(pd.DataFrame([{"mode": q["mode"], "questions": q["n_questions"],
                                    "execution accuracy": q["execution_accuracy"],
                                    "malicious blocked": q["malicious_blocked_rate"],
                                    "SQL attacks blocked": f"{q['sql_parser_attacks_blocked']}/{q['sql_parser_attacks']}"}]),
                     hide_index=True)
        st.json(q["accuracy_by_type"], expanded=False)
    with tabs[8]:
        st.json(cfg, expanded=False)
        rep = os.path.join(path, "report.md")
        if os.path.exists(rep):
            st.download_button("Download report.md", open(rep, "rb").read(), f"{run}_report.md", "text/markdown")


# ------------------------------------------------------------------ Settings / registry
def settings():
    svc = state.svc()
    T.header(
        "System Configuration",
        "Enterprise Parameters & Industry Profiles",
        "Configure supplier multi-criteria evaluation weights, corporate working capital limits, "
        "and industry retail sector profiles (Proposal Section 3)."
    )
    is_admin = svc.can(state.user(), "change_settings")
    a, b = st.columns(2)
    reg = svc.registry()
    with a:
        st.markdown("**Registered Autonomous Agents**")
        st.dataframe(pd.DataFrame([{"agent": k, "description": v} for k, v in reg["agents"].items()]), hide_index=True,
                     use_container_width=True)
        st.markdown("**Registered Deterministic Tools**")
        st.dataframe(pd.DataFrame([{"tool": k, "description": v} for k, v in reg["tools"].items()]), hide_index=True,
                     use_container_width=True)
        st.caption("Extensible: Add custom agents or tools via `procure/registry.py` without modifying orchestrator.")
    with b:
        env = svc.env
        st.markdown("**Corporate Governance & Operating Constraints**")
        spent = env.committed_spend()
        rem_budget = env.budget_cap - spent
        T.kv([
            ("Active Profile", T.esc((env.meta("profile") or "supermarket").title())),
            ("Service Level Target (z)", f"{env.profile['z']} (95% fill rate)"),
            ("Review Cycle", f"{env.profile['review']} days"),
            ("Working Capital Budget", T.money(env.budget_cap)),
            ("Committed Spend", T.money(spent)),
            ("Available Working Capital", f"${rem_budget:,.2f}"),
            ("Max PO Revisions", f"{MAX_REVISIONS} attempts"),
            ("ML Confidence Threshold", f"{LOW_CONFIDENCE:.2f}"),
            ("Safety Buffer Multiplier", f"+{(SAFETY_BUFFER - 1) * 100:.0f}%"),
            ("Execution Runtime", T.esc(env.llm.mode)),
        ])
        st.markdown("**Supplier Multi-Criteria Weights** (Score = Price + Lead Time + Reliability)")
        w = env.weights
        p = st.slider("Price Weight (Cost Sensitivity)", 0.0, 1.0, float(w["price"]), 0.05, disabled=not is_admin)
        ld = st.slider("Lead Time Weight (Delivery Speed)", 0.0, 1.0, float(w["lead"]), 0.05, disabled=not is_admin)
        r = st.slider("Reliability Weight (Historical Fill Rate)", 0.0, 1.0, float(w["reliability"]), 0.05,
                      disabled=not is_admin)
        c1, c2 = st.columns(2)
        if c1.button("Save Sourcing Weights", icon=":material/save:", disabled=not is_admin, type="primary"):
            try:
                applied = svc.set_weights(state.user(), {'price': p, 'lead': ld, 'reliability': r})
                st.success(f"Weights saved and normalized: {applied}")
            except (PermissionDenied, ValueError) as e:
                st.error(str(e))
        if c2.button("Reset Default Weights", icon=":material/restart_alt:", disabled=not is_admin):
            svc.set_weights(state.user(), dict(DEFAULT_WEIGHTS))
            st.rerun()
        if not is_admin:
            st.caption(
                "Read-only for Buyer and Approver roles. Switch to 'root (Administrator)' to adjust weights or reset data."
            )
    st.markdown("---")
    st.markdown("**Industry Retail Sector Profiles (Proposal Section 3)**")
    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown(
            '<div class="pa-card">'
            '<div style="font-weight:700; color:#0F766E; margin-bottom:4px;">🛒 Supermarket</div>'
            '<div style="font-size:0.85rem; color:#64748B;">High-velocity FMCG items, perishable batches with strict '
            'expiry tracking, daily customer demand cadence.</div>'
            '</div>',
            unsafe_allow_html=True
        )
    with p2:
        st.markdown(
            '<div class="pa-card">'
            '<div style="font-weight:700; color:#0F766E; margin-bottom:4px;">💊 Pharmacy</div>'
            '<div style="font-size:0.85rem; color:#64748B;">Pharmaceuticals, batch expiry compliance, non-negotiable '
            'service levels (99%), zero tolerance for stockouts.</div>'
            '</div>',
            unsafe_allow_html=True
        )
    with p3:
        st.markdown(
            '<div class="pa-card">'
            '<div style="font-weight:700; color:#0F766E; margin-bottom:4px;">🔧 Hardware Store</div>'
            '<div style="font-size:0.85rem; color:#64748B;">Lumpy and intermittent demand, bulky non-perishable goods, '
            'longer supplier delivery lead times.</div>'
            '</div>',
            unsafe_allow_html=True
        )
    c = st.columns([1, 1, 1, 1])
    seed = c[0].number_input("Random Seed", 1, 9999, 1, disabled=not is_admin)
    skus = c[1].number_input("Number of SKUs", 10, 500, 40, disabled=not is_admin)
    prof = c[2].selectbox("Select Sector Profile", ["supermarket", "pharmacy", "hardware"], disabled=not is_admin)
    c[3].write("")
    if c[3].button("Generate Fresh ERP Data", icon=":material/dataset:", disabled=not is_admin, use_container_width=True):
        state.reset(seed, skus, prof)
        st.success("New synthetic ERP dataset successfully generated.")
        st.rerun()
    with st.expander("Workflow Architecture Specification (Compiled LangGraph)", expanded=False, icon=":material/schema:"):
        st.caption("State machine graph compiled from LangGraph agent nodes and conditional edges:")
        st.code(mermaid(), language="text")
