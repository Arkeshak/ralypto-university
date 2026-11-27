"""ProcureAgents: Autonomous Inventory Optimization & Procurement with Human Sign-Off.

Production-ready commercial SaaS application for supermarkets, pharmacies, retail stores, and wholesale businesses.
"""
from __future__ import annotations

import os
import sys

# Ensure local packages are on path
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from procure.models import CaseFile, DraftPO  # noqa: E402
from ui import pages_eval, pages_gov, pages_ops, products, state  # noqa: E402
from ui import theme as T  # noqa: E402

st.set_page_config(page_title="ProcureAgents", page_icon=":material/inventory_2:", layout="wide",
                   initial_sidebar_state="expanded")
T.inject()


# ------------------------------------------------------------------ Guided Walkthrough
def demo():
    svc = state.svc()
    profile = str(svc.env.meta("profile") or "supermarket")
    T.header(
        "Executive Walkthrough",
        "Autonomous Procurement Demonstration",
        "Experience the end-to-end procurement cycle: Stock Shortfall Detection -> AI Demand Forecasting & Supplier Sourcing "
        "-> Order Formulation -> Safety Verification -> Manager Approval -> Activity History."
    )
    T.flow_banner(
        "How ProcureAgents Protects Retail Margins",
        "Retail stores lose up to 15% of annual revenue through manual spreadsheet guessing, stockouts, and expiry waste. "
        "ProcureAgents automates the planning and supplier negotiations while keeping store managers in full control.",
        [
            ("1", "Detect Risk", "Continuously monitors shelves for low stock or approaching expiration dates."),
            ("2", "AI Plans Order", "Predicts customer demand and ranks verified suppliers on price, speed, and reliability."),
            ("3", "Manager Signs Off", "Enforces budget caps and policy rules; store manager approves with 1 click.")
        ]
    )
    al = svc.alerts("alice")
    if not al:
        T.empty("No active alerts in the store catalog. Reset the demo database in Settings (admin).")
        return
    open_pos = svc.purchase_orders("bob")
    open_skus = {p["sku"] for p in open_pos if p["status"] in ("PENDING_APPROVAL", "CREATED")}
    unhandled = [a for a in al if a.sku not in open_skus]
    raw_pool = unhandled if unhandled else al

    # Sort alerts so that restock reorder cases appear first for live demonstration
    def _priority(a):
        kind_rank = 0 if a.kind == "stockout" else (1 if a.kind == "both" else 2)
        sev_rank = 0 if a.severity == "high" else (1 if a.severity == "medium" else 2)
        return (kind_rank, sev_rank, -a.on_hand)

    target_pool = sorted(raw_pool, key=_priority)

    if not unhandled:
        st.info("All alert items currently have orders drafted or approved. Click below to generate fresh demo data.",
                icon=":material/info:")
        if st.button("Generate Fresh Store Inventory", icon=":material/refresh:", type="primary"):
            state.reset(1, 40, profile)
            st.rerun()

    def _alert_label(a):
        pname, _, _ = products.get_product_visuals(a.sku, profile)
        tag = "Restock Needed" if a.kind == "stockout" else ("Dual Risk" if a.kind == "both" else "Clearance Markdown")
        return f"[{tag}] {pname} ({a.sku}) - Stock: {int(a.on_hand)} units | Min: {int(a.reorder_point)}"

    sku_picked = st.selectbox(
        "Select Product to Demonstrate",
        [a.sku for a in target_pool],
        format_func=lambda s: next((_alert_label(a) for a in target_pool if a.sku == s), s),
    )
    target = next((a for a in target_pool if a.sku == sku_picked), target_pool[0])

    v = products.get_product_visuals(target.sku)
    pname, pcat = v["name"], v["category"]
    st.markdown(
        f'<div class="pa-product-card">'
        f'<div style="display:flex; align-items:center; gap:16px;">'
        f'{products.product_avatar_html(target.sku, size=64)}'
        f'<div style="flex:1;">'
        f'<div style="display:flex; align-items:center; gap:8px;">'
        f'<span style="font-size:1.15rem; font-weight:700; color:#0F172A;">{pname}</span>'
        f'<span class="pa-badge pa-badge-critical">{target.severity.upper()} PRIORITY</span>'
        f'</div>'
        f'<div style="color:#64748B; font-size:0.88rem; margin-top:3px;">'
        f'Category: <b>{pcat}</b> • Product Code: <code>{target.sku}</code> • '
        f'Condition: <b>{target.kind.replace("_", " ").title()}</b>'
        f'</div>'
        f'<div style="color:#475569; font-size:0.85rem; margin-top:4px;">'
        f'Available Stock: <b>{int(target.on_hand)} units</b> • Reorder Point: <b>{int(target.reorder_point)} units</b> • '
        f'Sales Velocity: <b>{target.avg_daily:.1f} units/day</b>'
        f'</div></div></div></div>',
        unsafe_allow_html=True,
    )

    if not st.button("Run Live Procurement Demonstration", icon=":material/play_arrow:", type="primary"):
        st.caption("Executes all AI planning and safety steps live against the database. Real-time reasoning, no pre-recorded data.")
        return

    left, right = st.columns([3, 2])
    graph_slot = right.empty()
    visited: set = set()
    case: CaseFile | None = None
    with left:
        s1 = st.status("Phase 1: AI Market Analysis & Order Formulation (Purchasing Officer: Alice)", expanded=True)
        for kind, item in svc.run_case_stream("alice", target.sku):
            if kind == "msg":
                visited.add(getattr(item, "author", ""))
                pages_ops.render_step(item, s1)
                graph_slot.graphviz_chart(pages_ops.workflow_dot(visited, set()), use_container_width=True)
            elif kind == "case":
                case = item  # type: ignore[assignment]
        if case is None:
            s1.update(label="Analysis could not be completed", state="error")
            st.warning("No case result was produced. Please select another product above.")
            return
        s1.update(label=f"Phase 1 Complete: Proposal formulated ({case.status.replace('_', ' ').title()})",
                  state="complete" if case.status == "pending_approval" else "error")
        st.session_state["last_case"] = case.task_id
        if case.status != "pending_approval" or case.po_id is None or case.draft is None:
            if case.draft and case.draft.action == "markdown":
                T.callout(
                    f"**AI Optimization Outcome: Clearance Markdown Recommended**<br>"
                    f"The system analyzed <b>{pname}</b> and identified {int(target.on_hand)} units approaching expiration. "
                    f"Placing a restock order would create excess waste. "
                    f"Instead, the system formulated an immediate **{case.draft.markdown_pct}% clearance discount** to "
                    f"sell through shelf inventory before expiration.",
                    kind="tip",
                )
            else:
                T.callout(
                    "**AI Optimization Outcome: No Immediate Purchase Needed**<br>"
                    "Current shelf stock and incoming orders are sufficient to cover forecasted customer demand. "
                    "The system prevented unnecessary working capital expenditure.",
                    kind="info",
                )
            st.info(
                "Tip: To see the full Purchase Order Creation and Manager Sign-Off cycle, "
                "select a **[Restock Needed]** item from the dropdown above.",
                icon=":material/lightbulb:",
            )
            return
        po_id: int = case.po_id
        draft: DraftPO = case.draft
        s2 = st.status("Phase 2: Human-in-the-Loop Governance & Authorization", expanded=True)
        with s2:
            try:
                svc.approve("alice", po_id)
                st.error("A purchasing officer approved a PO - this must never happen under Maker-Checker rules.")
            except Exception:
                T.callout(
                    "**Maker-Checker Rule Enforced:** Purchasing Officer 'alice' attempted unauthorized self-approval and "
                    "was safely blocked by corporate security policy. Only authorized Store Managers (Bob) "
                    "can commit company capital.",
                    kind="info",
                )
            st.write(f"Store Manager 'bob' reviews Purchase Order #{po_id}: {draft.qty} units from {draft.supplier_name} "
                     f"(@ ${draft.unit_price:.2f}/unit) = **${draft.total:,.2f}**")
            res = svc.approve("bob", po_id, "Authorized in executive walkthrough")
            st.success(f"Purchase Order #{po_id} Authorized & Committed to ERP (Status: {res})")
        s2.update(label=f"Phase 2 Complete: Authorized by Store Manager Bob (PO #{po_id})", state="complete")
        visited.add("human_approver")
        graph_slot.graphviz_chart(pages_ops.workflow_dot(visited, set()), use_container_width=True)
        st.markdown("#### Phase 3: Verified Activity History & Official Documents")
        st.caption(
            "Every calculation, supplier quote comparison, timestamp, and manager approval "
            "is permanently recorded to an immutable audit ledger."
        )
        trail = pd.DataFrame(svc.audit("bob", po_id=po_id))
        st.dataframe(trail[["id", "ts", "actor", "action", "detail"]], hide_index=True, use_container_width=True)
        d1, d2, _ = st.columns([1, 1, 2])
        d1.download_button("Download Official PO (PDF)", svc.po_pdf("bob", po_id), f"PO_{po_id}.pdf", "application/pdf",
                           icon=":material/picture_as_pdf:")
        d2.download_button("Export Order Line Items (CSV)", svc.po_csv("bob", po_id), f"PO_{po_id}.csv", "text/csv",
                           icon=":material/download:")


# ------------------------------------------------------------------ Navigation
P = {
    "overview": st.Page(pages_ops.overview, title="Store Dashboard", icon=":material/dashboard:", url_path="overview",
                        default=True),
    "inventory": st.Page(pages_ops.inventory, title="Product Inventory", icon=":material/inventory_2:", url_path="inventory"),
    "alerts": st.Page(pages_ops.alerts, title="Stock Alerts", icon=":material/notifications:", url_path="alerts"),
    "agent_run": st.Page(pages_ops.agent_run, title="Purchasing Assistant", icon=":material/smart_toy:", url_path="agent-run"),
    "approvals": st.Page(pages_gov.approvals, title="Manager Approvals", icon=":material/fact_check:",
                         url_path="approvals"),
    "ask": st.Page(pages_gov.ask, title="AI Business Assistant", icon=":material/chat:", url_path="ask"),
    "audit": st.Page(pages_gov.audit, title="Activity History", icon=":material/history:", url_path="audit"),
    "benchmark": st.Page(pages_eval.benchmark, title="ROI & Accuracy", icon=":material/monitoring:",
                         url_path="benchmark"),
    "settings": st.Page(pages_eval.settings, title="Store Settings", icon=":material/tune:", url_path="settings"),
    "demo": st.Page(demo, title="Guided Walkthrough", icon=":material/play_circle:", url_path="demo"),
}
pages_ops.PAGES.update(P)

nav = st.navigation({
    "Store Operations": [P["overview"], P["inventory"], P["alerts"]],
    "Purchasing & Approvals": [P["agent_run"], P["approvals"]],
    "Store Management": [P["ask"], P["audit"], P["benchmark"], P["settings"], P["demo"]],
})

with st.sidebar:
    st.markdown("### ProcureAgents")
    st.caption("Intelligent Inventory & Procurement")
    svc = state.svc()
    users = svc.users()
    names = list(users)
    current = st.session_state.get("acting_user", "alice")
    picked = st.selectbox("Current User (Role)", names, index=names.index(current) if current in names else 0,
                          format_func=lambda n: f"{n.capitalize()} ({users[n].title()})")
    user_name = str(picked or "alice")
    st.session_state["acting_user"] = user_name

    # Role switcher button & explanation
    role_desc = {
        "alice": "Purchasing Officer: Formulates restock plans & drafts orders (cannot self-approve).",
        "bob": "Store Manager: Reviews AI proposals & holds executive sign-off authority.",
        "root": "Administrator: Manages company budgets, supplier rules & system settings.",
    }
    st.caption(role_desc.get(user_name, f"Role: {users.get(user_name, 'user')}"))

    if user_name == "alice":
        if st.button("Switch to Bob (Store Manager)", icon=":material/person_check:", use_container_width=True):
            st.session_state["acting_user"] = "bob"
            st.rerun()
    elif user_name == "bob":
        if st.button("Switch to Alice (Purchasing Officer)", icon=":material/shopping_cart:", use_container_width=True):
            st.session_state["acting_user"] = "alice"
            st.rerun()

    profile_name = str(svc.env.meta("profile") or "supermarket").title()
    st.markdown(f'<div class="pa-mode">Mode: {T.esc(svc.env.llm.mode)}<br>Store Day: {svc.env.today} • '
                f'{T.esc(profile_name)} Profile</div>', unsafe_allow_html=True)
    st.write("")
    if st.button("Launch Guided Tour", icon=":material/play_arrow:", type="primary", use_container_width=True):
        st.switch_page(P["demo"])

    st.markdown("---")
    st.markdown(
        "<div style='font-size:0.78rem; color:#A2B7BA; line-height:1.45;'>"
        "<b>Core Procurement Workflow:</b><br>"
        "1. <b>Stock Alerts:</b> Detect shortages & expiry risks<br>"
        "2. <b>AI Assistant:</b> Predict demand & source best suppliers<br>"
        "3. <b>Manager Desk:</b> Human sign-off before funds commit"
        "</div>",
        unsafe_allow_html=True,
    )


nav.run()
