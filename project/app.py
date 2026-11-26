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

from procure.models import CaseFile, DraftPO, Message  # noqa: E402
from ui import pages_eval, pages_gov, pages_ops, state  # noqa: E402
from ui import theme as T  # noqa: E402

st.set_page_config(page_title="ProcureAgents", page_icon=":material/inventory_2:", layout="wide",
                   initial_sidebar_state="expanded")
T.inject()


# ------------------------------------------------------------------ guided end-to-end demo
def demo():
    svc = state.svc()
    T.header("Live demo", "End-to-end purchasing case",
             "Alert -> Forecasting + Supplier in parallel -> Purchase Order -> Validator -> human approval -> PO "
             "created -> audit log. The buyer (alice) starts the case; the approver (bob) decides.")
    al = svc.alerts("alice")
    if not al:
        T.empty("No alerts in the current ERP. Regenerate the data in Settings (admin).")
        return
    target = next((a for a in al if a.kind in ("low_stock", "both")), al[0])
    st.markdown(
        f'<div class="pa-card">'
        f'<div style="font-size:1.05rem; font-weight:700; margin-bottom:4px;">Target Item: <code>{target.sku}</code> '
        f'{T.pill(target.severity)}</div>'
        f'<div style="color:#64748B; font-size:0.88rem;">'
        f'Condition: <b>{target.kind.replace("_", " ").title()}</b> • '
        f'Stock on hand: <b>{int(target.on_hand)} units</b> • '
        f'Reorder threshold: <b>{int(target.reorder_point)} units</b> • '
        f'Daily sales: <b>{target.avg_daily:.1f} units/day</b>'
        f'</div></div>',
        unsafe_allow_html=True,
    )
    if not st.button("Play the full case", type="primary"):
        st.caption("The button runs every step for real against the synthetic ERP; nothing is pre-recorded.")
        return
    left, right = st.columns([3, 2])
    graph_slot = right.empty()
    visited: set = set()
    case: CaseFile | None = None
    with left:
        s1 = st.status("Step 1-4: agents run as buyer 'alice'", expanded=True)
        for kind, item in svc.run_case_stream("alice", target.sku):
            if kind == "msg" and isinstance(item, Message):
                visited.add(item.author)
                pages_ops.render_step(item, s1)
                graph_slot.graphviz_chart(pages_ops.workflow_dot(visited, set()), use_container_width=True)
            elif isinstance(item, CaseFile):
                case = item
        if case is None:
            st.warning("No case result was produced. Try another alert.")
            return
        s1.update(label=f"Agents finished: {case.status}", state="complete")
        st.session_state["last_case"] = case.task_id
        if case.status != "pending_approval" or case.po_id is None or case.draft is None:
            st.warning(f"The case ended as '{case.status}' ({'; '.join(case.notes)}). Try another alert.")
            return
        po_id: int = case.po_id
        draft: DraftPO = case.draft
        s2 = st.status("Step 5: approval attempts", expanded=True)
        with s2:
            try:
                svc.approve("alice", po_id)
                st.error("A buyer approved a PO - this must never happen.")
            except Exception:
                T.callout(
                    "<b>Security Gate Verified:</b> Buyer 'alice' attempted unauthorized self-approval and "
                    "was safely blocked by governance policy (only Approvers can authorize purchases).",
                    kind="info",
                )
            st.write(f"Approver 'bob' reviews PO #{po_id}: {draft.qty} x {draft.supplier_name} = "
                     f"{T.money(draft.total)}")
            res = svc.approve("bob", po_id, "approved in live demo")
            st.success(f"PO #{po_id} -> {res}")
        s2.update(label=f"Step 5: approved by bob, PO #{po_id} {res}", state="complete")
        visited.add("human_approver")
        graph_slot.graphviz_chart(pages_ops.workflow_dot(visited, set()), use_container_width=True)
        st.markdown("**Step 6: audit trail for this PO** (append-only)")
        trail = pd.DataFrame(svc.audit("bob", po_id=po_id))
        st.dataframe(trail[["id", "ts", "actor", "action", "detail"]], hide_index=True, use_container_width=True)
        d1, d2, _ = st.columns([1, 1, 3])
        d1.download_button("PO as PDF", svc.po_pdf("bob", po_id), f"PO_{po_id}.pdf", "application/pdf")
        d2.download_button("PO as CSV", svc.po_csv("bob", po_id), f"PO_{po_id}.csv", "text/csv")


# ------------------------------------------------------------------ navigation
P = {
    "overview": st.Page(pages_ops.overview, title="Overview", icon=":material/dashboard:", url_path="overview",
                        default=True),
    "alerts": st.Page(pages_ops.alerts, title="Alerts and cases", icon=":material/notifications:", url_path="alerts"),
    "agent_run": st.Page(pages_ops.agent_run, title="Agent run", icon=":material/account_tree:", url_path="agent-run"),
    "approvals": st.Page(pages_gov.approvals, title="Approval dashboard", icon=":material/fact_check:",
                         url_path="approvals"),
    "ask": st.Page(pages_gov.ask, title="Ask the data", icon=":material/chat:", url_path="ask"),
    "audit": st.Page(pages_gov.audit, title="Audit log", icon=":material/history:", url_path="audit"),
    "benchmark": st.Page(pages_eval.benchmark, title="Benchmark results", icon=":material/monitoring:",
                         url_path="benchmark"),
    "settings": st.Page(pages_eval.settings, title="Settings and registry", icon=":material/tune:", url_path="settings"),
    "demo": st.Page(demo, title="Live demo", icon=":material/play_circle:", url_path="demo"),
}
pages_ops.PAGES.update(P)
nav = st.navigation({
    "Getting Started": [P["demo"], P["overview"]],
    "Purchasing Operations": [P["alerts"], P["agent_run"], P["approvals"]],
    "Governance & Intelligence": [P["ask"], P["audit"], P["benchmark"], P["settings"]],
})

with st.sidebar:
    st.markdown("### ProcureAgents")
    st.caption("Team Ralypto • Innodata Catalyst '26")
    svc = state.svc()
    users = svc.users()
    names = list(users)
    current = st.session_state.get("acting_user", "alice")
    picked = st.selectbox("Acting user (role)", names, index=names.index(current) if current in names else 0,
                          format_func=lambda n: f"{n} ({users[n]})")
    user_name = str(picked or "alice")
    st.session_state["acting_user"] = user_name

    # Quick role switcher button & explanation
    role_desc = {
        "alice": "Buyer: Authorized to initiate cases & draft POs (cannot self-approve).",
        "bob": "Approver: Authorized to review, modify & approve pending POs.",
        "root": "Administrator: System configuration & environment reset.",
    }
    st.caption(role_desc.get(user_name, f"Role: {users.get(user_name, 'user')}"))

    if user_name == "alice":
        if st.button("Switch to Bob (Approver)", icon=":material/person_check:", use_container_width=True):
            st.session_state["acting_user"] = "bob"
            st.rerun()
    elif user_name == "bob":
        if st.button("Switch to Alice (Buyer)", icon=":material/shopping_cart:", use_container_width=True):
            st.session_state["acting_user"] = "alice"
            st.rerun()

    st.markdown(f'<div class="pa-mode">Mode: {T.esc(svc.env.llm.mode)}<br>ERP day {svc.env.today} - '
                f'{T.esc(svc.env.meta("profile"))}</div>', unsafe_allow_html=True)
    st.write("")
    if st.button("Run Guided Demo", icon=":material/play_arrow:", type="primary", use_container_width=True):
        st.switch_page(P["demo"])

    st.markdown("---")
    st.markdown(
        "<div style='font-size:0.78rem; color:#A2B7BA; line-height:1.45;'>"
        "<b>ProcureAgents Workflow:</b><br>"
        "1. <b>Overview & Alerts:</b> Detect stockout & expiry risks<br>"
        "2. <b>Agent Orchestration:</b> Multi-agent planning & forecasting<br>"
        "3. <b>Approval Gate:</b> Human-in-the-loop authorization"
        "</div>",
        unsafe_allow_html=True,
    )


nav.run()
