# Project Workflow

## 1. Problem definition
- Domain: Logistics (inventory replenishment and procurement)
- Problem: manual, reactive purchasing causes stockouts, overstock and expiry losses; chatbots cannot be trusted to act on ERP data.
- Users: purchasing officers, store managers, approvers/owners, auditors.
- Evidence: `Proposal.docx` (IHL Group 2023, UNEP Food Waste Index 2024, World Bank, Anthropic, Cemri et al. 2025).

## 2. Implemented workflow (`project/procure/orchestrator.py`)
1. Trigger: a SKU and a requester (role checked by the Validator).
2. Stock Monitor raises a low-stock and/or expiry alert; no alert ends the case.
3. Forecasting and Supplier agents run in parallel; if the forecaster fails, the reorder-point fallback is used.
4. Purchase Order agent combines forecast and ranking into a draft, or recommends markdown if usable stock covers demand.
5. Validator checks role, price, stock, MOQ, sanity and budget. A failure goes back to the PO agent (max 2 revisions); otherwise the case is escalated to a human.
6. The safe-action gate stores the PO as PENDING_APPROVAL (idempotency key, audit rows).
7. A human approver (`main.py approve ID`) approves or rejects; only then is the PO CREATED. A created PO can be cancelled.
8. Every step is in the JSONL trace and the audit table.

PO states: DRAFT -> VALIDATED -> PENDING_APPROVAL -> APPROVED -> CREATED (-> CANCELLED); REJECTED from DRAFT or PENDING_APPROVAL.

## 3. Multi-agent interaction
See the architecture table in `PROJECT_DETAILS.md`. Execution evidence: run `python project/main.py demo` and read `project/results/demo_trace.jsonl`. Each line is a structured message; the PO agent consumes the Forecast and Supplier outputs and the Validator consumes the draft.

## 4. Baselines and evaluation
`python project/main.py bench` runs system A (multi-agent) and D (rule-based) on identical seeded scenarios, plus forecast WAPE, the safety suite, a 50-question query set and 50/500/5,000-SKU scalability. System B (single LLM agent) is in `baselines.py` and runs automatically when `LLM_PROVIDER`, `LLM_MODEL` and `LLM_API_KEY` are set. System C (human) needs volunteers and has not been run. Results and limitations are in `PROJECT_DETAILS.md`.

## 5. Reliability and safety
Read-only agent DB connection; SQL allow-list; RBAC and state machine in the gate; idempotent submit; append-only audit via triggers; LLM retries and timeouts with deterministic fallbacks; typed messages; injection screening of supplier text; tests in `project/tests`.

## 6. Implementation milestones
| Milestone | Status |
|---|---|
| Confirm problem and research | Done (proposal) |
| Finalize architecture and agent roles | Done |
| Build end-to-end Phase 1 prototype | Done (CLI, deterministic mode) |
| Implement single-agent baseline | Code done, not run (needs LLM) |
| Run human and system evaluations | A and D run; B and human not run |
| Document results and limitations | Done for what was run |
| Streamlit UI, FastAPI layer, LangGraph, LightGBM | Not started |
