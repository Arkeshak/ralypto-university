"""ProcureAgents - Streamlit UI (Team Ralypto, Innodata AI Catalyst '26).

Run:  python project/main.py serve        (or: streamlit run project/app.py)

Pages: Overview, Alerts and cases, Agent run, Approval dashboard, Ask the data,
Audit log, Benchmark results, Settings and registry, plus a guided live demo.
The role switcher selects a real ERP user; every permission is enforced by the
service layer (procure/service.py) and again by the safe-action gate.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from procure.models import CaseFile, DraftPO  # noqa: E402
from ui import pages_eval, pages_gov, pages_ops, state  # noqa: E402
from ui import theme as T  # noqa: E402

st.set_page_config(page_title="ProcureAgents", page_icon=":material/inventory_2:", layout="wide",
                   initial_sidebar_state="expanded")
T.inject()


# ------------------------------------------------------------------ guided end-to-end demo
def demo():
    svc = state.svc()
    T.header(
        "Executive Walkthrough",
        "Autonomous Procurement Demonstration",
        "Experience the full procurement cycle: Inventory Shortfall Detection -> Demand Forecasting + Supplier Sourcing "
        "-> Order Formulation -> Compliance Verification -> Human Manager Approval -> Immutable Audit Logging."
    )
    T.flow_banner(
        "How ProcureAgents Solves Inventory Distortion",
        "Small and medium businesses lose revenue to stockouts and expiry waste through manual spreadsheet guessing. "
        "ProcureAgents automates the planning while keeping the human manager in 100% control.",
        [
            ("1", "Detect Shortfall", "Stock Monitor identifies products falling below safety stock or nearing expiration."),
            ("2", "AI Agents Plan", "Demand Forecaster (LightGBM) & Supplier Intelligence formulate the best order in parallel."),
            ("3", "Executive Signs Off", "Policy Validator verifies budget caps; Store Manager authorizes the purchase.")
        ]
    )
    al = svc.alerts("alice")
    if not al:
        T.empty("No alerts in the current ERP. Regenerate the data in Settings (admin).")
        return
    open_pos = svc.purchase_orders("bob")
    open_skus = {p["sku"] for p in open_pos if p["status"] in ("PENDING_APPROVAL", "CREATED")}
    unhandled = [a for a in al if a.sku not in open_skus]
    raw_pool = unhandled if unhandled else al

    # Sort alerts so that guaranteed restock reorder cases appear at the top for live demonstration
    def _priority(a):
        kind_rank = 0 if a.kind == "stockout" else (1 if a.kind == "both" else 2)
        sev_rank = 0 if a.severity == "high" else (1 if a.severity == "medium" else 2)
        return (kind_rank, sev_rank, -a.on_hand)

    target_pool = sorted(raw_pool, key=_priority)

    if not unhandled:
        st.info("All alert items currently have orders drafted or created in the ERP. Click below to reset fresh demo data.",
                icon=":material/info:")
        if st.button("Reset Synthetic ERP for Clean Replay", icon=":material/refresh:", type="primary"):
            state.reset(1, 40, "supermarket")
            st.rerun()

    def _alert_label(a):
        tag = "Restock Order" if a.kind == "stockout" else ("Dual Risk" if a.kind == "both" else "Clearance Markdown")
        return (f"[{tag}] {a.sku} ({a.severity.title()} Priority) - "
                f"On Hand: {int(a.on_hand)} units | Safety Threshold: {int(a.reorder_point)} units")

    sku_picked = st.selectbox(
        "Choose Item Alert to Demonstrate",
        [a.sku for a in target_pool],
        format_func=lambda s: next((_alert_label(a) for a in target_pool if a.sku == s), s),
    )
    target = next((a for a in target_pool if a.sku == sku_picked), target_pool[0])
    st.markdown(
        f'<div class="pa-card">'
        f'<div style="font-size:1.05rem; font-weight:700; margin-bottom:4px;">Target Product: <code>{target.sku}</code> '
        f'{T.pill(target.severity)}</div>'
        f'<div style="color:#64748B; font-size:0.88rem;">'
        f'Risk Condition: <b>{target.kind.replace("_", " ").title()}</b> • '
        f'Stock on Hand: <b>{int(target.on_hand)} units</b> • '
        f'Safety Threshold: <b>{int(target.reorder_point)} units</b> • '
        f'Average Daily Demand: <b>{target.avg_daily:.1f} units/day</b>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    if not st.button("Run Live Procurement Demonstration", icon=":material/play_arrow:", type="primary"):
        st.caption("Runs every agent step live against the ERP database. Real-time reasoning, no pre-recorded data.")
        return
    left, right = st.columns([3, 2])
    graph_slot = right.empty()
    visited: set = set()
    case: CaseFile | None = None
    with left:
        s1 = st.status("Phase 1: Multi-Agent Analysis & Order Formulation (Buyer: Alice)", expanded=True)
        for kind, item in svc.run_case_stream("alice", target.sku):
            if kind == "msg":
                visited.add(getattr(item, "author", ""))
                pages_ops.render_step(item, s1)
                graph_slot.graphviz_chart(pages_ops.workflow_dot(visited, set()), use_container_width=True)
            elif kind == "case":
                case = item  # type: ignore[assignment]
        if case is None:
            s1.update(label="Analysis could not be completed", state="error")
            st.warning("No case result was produced. Please select another alert above.")
            return
        s1.update(label=f"Phase 1 Complete: Recommendation formulated ({case.status.replace('_', ' ').title()})",
                  state="complete" if case.status == "pending_approval" else "error")
        st.session_state["last_case"] = case.task_id
        if case.status != "pending_approval" or case.po_id is None or case.draft is None:
            if case.draft and case.draft.action == "markdown":
                T.callout(
                    f"**AI Optimization Outcome: Inventory Clearance & Markdown Recommended**<br>"
                    f"The agents analyzed product <code>{case.sku}</code> and identified that {int(target.on_hand)} "
                    f"units are nearing expiration. Placing a new supplier order would create excess inventory write-off. "
                    f"Instead, the system formulated an immediate **{case.draft.markdown_pct}% price discount** to "
                    f"liquidate shelf stock before expiration.",
                    kind="tip",
                )
            else:
                T.callout(
                    "**AI Optimization Outcome: No Immediate Purchase Needed**<br>"
                    "Current pipeline stock or existing open orders are already sufficient to cover forecasted customer demand. "
                    "The system intelligently prevented unnecessary working capital expenditure.",
                    kind="info",
                )
            st.info(
                "Tip: To see the full Purchase Order Creation and Human Manager Sign-Off cycle, "
                "select a **[Restock Order]** item from the dropdown above.",
                icon=":material/lightbulb:",
            )
            return
        po_id: int = case.po_id
        draft: DraftPO = case.draft
        s2 = st.status("Phase 2: Human-in-the-Loop Governance & Authorization", expanded=True)
        with s2:
            try:
                svc.approve("alice", po_id)
                st.error("A buyer approved a PO - this must never happen.")
            except Exception:
                T.callout(
                    "**Governance Rule Enforced:** Buyer 'alice' attempted unauthorized self-approval and "
                    "was safely blocked by corporate security policy. Only authorized Approvers (Bob) "
                    "can commit company capital.",
                    kind="info",
                )
            st.write(f"Store Manager 'bob' reviews Purchase Order #{po_id}: {draft.qty} units from {draft.supplier_name} "
                     f"(@ ${draft.unit_price:.2f}/unit) = **${draft.total:,.2f}**")
            res = svc.approve("bob", po_id, "Authorized in executive walkthrough")
            st.success(f"Purchase Order #{po_id} Authorized & Committed to ERP (Status: {res})")
        s2.update(label=f"Phase 2 Complete: Authorized by Manager Bob (PO #{po_id})", state="complete")
        visited.add("human_approver")
        graph_slot.graphviz_chart(pages_ops.workflow_dot(visited, set()), use_container_width=True)
        st.markdown("#### Phase 3: Verified Audit Ledger & Commercial Documents")
        st.caption(
            "Every calculation, supplier quote comparison, timestamp, and manager approval "
            "is permanently recorded to an append-only ledger."
        )
        trail = pd.DataFrame(svc.audit("bob", po_id=po_id))
        st.dataframe(trail[["id", "ts", "actor", "action", "detail"]], hide_index=True, use_container_width=True)
        d1, d2, _ = st.columns([1, 1, 2])
        d1.download_button("Download Official PO (PDF)", svc.po_pdf("bob", po_id), f"PO_{po_id}.pdf", "application/pdf",
                           icon=":material/picture_as_pdf:")
        d2.download_button("Export Order Line Items (CSV)", svc.po_csv("bob", po_id), f"PO_{po_id}.csv", "text/csv",
                           icon=":material/download:")


# ------------------------------------------------------------------ navigation
P = {
    "overview": st.Page(pages_ops.overview, title="Executive Overview", icon=":material/dashboard:", url_path="overview",
                        default=True),
    "alerts": st.Page(pages_ops.alerts, title="Inventory Restock Alerts", icon=":material/notifications:", url_path="alerts"),
    "agent_run": st.Page(pages_ops.agent_run, title="AI Purchasing Assistant", icon=":material/smart_toy:", url_path="agent-run"),
    "approvals": st.Page(pages_gov.approvals, title="Manager Approval Gate", icon=":material/fact_check:",
                         url_path="approvals"),
    "ask": st.Page(pages_gov.ask, title="Natural Language Analytics", icon=":material/chat:", url_path="ask"),
    "audit": st.Page(pages_gov.audit, title="Compliance & Audit Trail", icon=":material/history:", url_path="audit"),
    "benchmark": st.Page(pages_eval.benchmark, title="ROI & Model Evaluation", icon=":material/monitoring:",
                         url_path="benchmark"),
    "settings": st.Page(pages_eval.settings, title="Company Configuration", icon=":material/tune:", url_path="settings"),
    "demo": st.Page(demo, title="Interactive Guided Tour", icon=":material/play_circle:", url_path="demo"),
}
pages_ops.PAGES.update(P)
nav = st.navigation({
    "Client Showcase": [P["demo"], P["overview"]],
    "Supply Chain Operations": [P["alerts"], P["agent_run"], P["approvals"]],
    "Governance & Business Intelligence": [P["ask"], P["audit"], P["benchmark"], P["settings"]],
})

with st.sidebar:
    st.markdown("### ProcureAgents")
    st.caption("Team Ralypto • University of Kelaniya")
    svc = state.svc()
    users = svc.users()
    names = list(users)
    current = st.session_state.get("acting_user", "alice")
    picked = st.selectbox("Current User (Role)", names, index=names.index(current) if current in names else 0,
                          format_func=lambda n: f"{n} ({users[n].title()})")
    user_name = str(picked or "alice")
    st.session_state["acting_user"] = user_name

    # Quick role switcher button & explanation
    role_desc = {
        "alice": "Buyer: Formulates restock plans & drafts orders (cannot self-approve).",
        "bob": "Store Manager: Reviews AI proposals & holds executive sign-off authority.",
        "root": "Administrator: Manages company budgets, supplier weights & data reset.",
    }
    st.caption(role_desc.get(user_name, f"Role: {users.get(user_name, 'user')}"))

    if user_name == "alice":
        if st.button("Switch to Bob (Store Manager)", icon=":material/person_check:", use_container_width=True):
            st.session_state["acting_user"] = "bob"
            st.rerun()
    elif user_name == "bob":
        if st.button("Switch to Alice (Buyer)", icon=":material/shopping_cart:", use_container_width=True):
            st.session_state["acting_user"] = "alice"
            st.rerun()

    profile_name = str(svc.env.meta("profile") or "supermarket").title()
    st.markdown(f'<div class="pa-mode">Mode: {T.esc(svc.env.llm.mode)}<br>ERP day {svc.env.today} - '
                f'{T.esc(profile_name)}</div>', unsafe_allow_html=True)
    st.write("")
    if st.button("Launch Guided Tour", icon=":material/play_arrow:", type="primary", use_container_width=True):
        st.switch_page(P["demo"])

    st.markdown("---")
    st.markdown(
        "<div style='font-size:0.78rem; color:#A2B7BA; line-height:1.45;'>"
        "<b>ProcureAgents Workflow:</b><br>"
        "1. <b>Alerts:</b> Detect stockout & expiry risks<br>"
        "2. <b>AI Agents:</b> Multi-agent forecasting & supplier sourcing<br>"
        "3. <b>Approval Gate:</b> Human manager authorization before purchase"
        "</div>",
        unsafe_allow_html=True,
    )


nav.run()
