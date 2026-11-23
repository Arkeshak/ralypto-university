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
    st.markdown(f"Selected alert: **{target.sku}** - severity {T.pill(target.severity)} - {target.kind} - "
                f"{T.esc(target.evidence)}", unsafe_allow_html=True)
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
            except Exception as e:
                T.blocked(f"Buyer 'alice' tried to approve: {e}")
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
nav = st.navigation({"Operate": [P["overview"], P["alerts"], P["agent_run"], P["approvals"]],
                     "Data and governance": [P["ask"], P["audit"]],
                     "Evaluate and configure": [P["benchmark"], P["settings"], P["demo"]]})

with st.sidebar:
    st.markdown("### ProcureAgents")
    st.caption("Team Ralypto - Innodata AI Catalyst '26")
    svc = state.svc()
    users = svc.users()
    names = list(users)
    current = st.session_state.get("acting_user", "alice")
    picked = st.selectbox("Acting user (role)", names, index=names.index(current) if current in names else 0,
                          format_func=lambda n: f"{n} ({users[n]})")
    user_name = str(picked or "alice")
    st.session_state["acting_user"] = user_name
    can = [a for a in ["run_case", "approve", "change_settings"] if svc.can(user_name, a)]
    st.caption("Can: view, query" + (", " + ", ".join(x.replace("_", " ") for x in can) if can else ""))
    st.markdown(f'<div class="pa-mode">Mode: {T.esc(svc.env.llm.mode)}<br>ERP day {svc.env.today} - '
                f'{T.esc(svc.env.meta("profile"))}</div>', unsafe_allow_html=True)
    st.write("")
    if st.button("Run demo scenario", use_container_width=True):
        st.switch_page(P["demo"])

nav.run()
