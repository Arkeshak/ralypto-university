# Project Details

> Technical record and third-party/AI-tool disclosure register. Kept in sync with the code in `project/`.

## Project overview
- Team: Ralypto, University of Kelaniya
- Competition: Innodata AI Catalyst '26, University Track
- Project title: **ProcureAgents**: a safe, auditable multi-agent system for inventory and procurement decisions in ERP
- Industry domain: Logistics (supply-chain inventory replenishment and procurement)
- Problem: small and mid-size businesses decide what/how much/from whom to reorder by hand, causing stockouts, overstock and expiry (see `Proposal.docx`).
- Target users: purchasing officers, store managers, approvers/owners, auditors.

## Objectives
Cut stockouts and expiry losses with explainable recommendations; keep every action safe (human approval, rule validation, RBAC, audit trail); answer plain-language data questions through a read-only validated path; measure multi-agent against baselines honestly.

## Features and functionality (status is accurate)
| Feature | Status |
|---|---|
| Seeded synthetic ERP (SQLite): seasonality, promotions, supplier delays, new items, optional corrupted history, a supplier note containing prompt-injection text | Implemented |
| Stock Monitor, Demand Forecasting, Supplier, Purchase Order, Validator agents, Orchestrator | Implemented |
| Typed shared case file (Pydantic), structured messages, JSONL trace | Implemented |
| Parallel Forecasting and Supplier branches; validator veto; max 2 revisions; escalation to human | Implemented |
| Safe-action gate: single write path, PO state machine, role checks, idempotency keys, rollback (cancel), append-only audit (DB triggers) | Implemented |
| Read-only Query Agent: SQL allow-list parser plus read-only DB connection | Implemented. Offline mode uses a template translator; the LLM text-to-SQL path is untested against a live model |
| Deterministic fallback (reorder-point policy) when the forecaster fails | Implemented |
| Provider-agnostic LLM wrapper (retries, timeout, token/cost counters); LLM only writes rationale text or advisory critique | Implemented, **never run against a live API** |
| System B single-agent LLM baseline (same tools, validator, gate) | Implemented, **not run** (needs LLM credentials) |
| Evaluation harness: replay simulation, oracle PO accuracy, WAPE, safety suite, 50-question query set, scalability, bootstrap CIs | Implemented |
| Business-type profiles (supermarket, pharmacy, hardware) | Implemented: configurable in CLI (`--profile`), sets categories, perishability, service level, and review period |
| Plug-in agent & tool registry | Implemented (`procure/registry.py`): modular registration and dynamic swapping of agents without modifying orchestrator |
| Streamlit chat panel and approval dashboard | Implemented (`project/app.py`) |
| Human purchaser comparison (System C) | Implemented (`procure/human_study.py`, CLI `main.py study`): 10-scenario protocol measuring latency and accuracy against oracle/replay |
| Supplier recommendation distribution (fairness & bias) | Implemented: tracked in benchmark summary and displayed in Streamlit evaluation dashboard |
| Sinhala/Tamil input | Future work |

## Multi-agent architecture
| Agent | Responsibility | Inputs -> outputs | Tools / permissions |
|---|---|---|---|
| Orchestrator (`orchestrator.py`) | Routes, runs branches in parallel, settles conflicts, escalates | task -> case file | Read-only env; calls the gate only after validation |
| Stock Monitor | Low-stock and expiry alerts | stock, batches -> `Alert` | Read-only SQL |
| Demand Forecasting | Daily forecast, sigma, confidence | sales history -> `Forecast` | Code only (weekly-seasonal x exponential smoothing); drops corrupt rows |
| Supplier | Weighted ranking (price .45, lead .20, reliability .35; adjustable), top 2 | price lists -> `SupplierRanking` | Read-only; supplier notes screened for injection and never obeyed |
| Purchase Order | Quantity from forecast, safety stock, usable (non-expiring) stock, MOQ; revises on validator feedback | alert + forecast + ranking -> `DraftPO` | Pure computation; LLM text discarded if it omits the computed quantity |
| Validator | Independent rules: role, listed price, stock, MOQ, sanity, budget; veto | draft -> `Validation` | Read-only; rule engine decides, LLM critique is advisory |
| Query Agent | NL -> checked SELECT -> answer | question -> rows | Parser allow-list plus read-only connection |
| Human Approver | Approve or reject | pending PO -> decision | Only `approver`/`admin` role, via the gate |

**Communication:** agents read and write the typed `CaseFile`; every step emits a `Message` (task id, author, inputs, output, confidence, evidence) to JSONL (`project/results/demo_trace.jsonl`). The PO agent consumes both Forecast and Supplier outputs; the Validator consumes the PO draft.
**Conflict handling:** validator veto -> up to two revisions (MOQ raise, budget trim, then alternate supplier) -> human escalation; forecast confidence below 0.5 -> +25% safety buffer and review flag; LLM text disagreeing with the numbers -> numbers win.
**Failure handling:** forecaster failure -> reorder-point fallback; LLM calls retry with back-off and return `None`, and every caller has a deterministic fallback.

## Technology stack
| Area | Technology | Purpose | Status |
|---|---|---|---|
| Language | Python 3.10+ | Runtime | Used |
| Typed state | Pydantic 2 | Case file and messages | Used |
| Data | SQLite (stdlib) | Synthetic ERP, audit | Used |
| Orchestration | Own state machine + `ThreadPoolExecutor` | Routing, parallel branches | Used. **LangGraph from the proposal was not used** |
| Forecasting | Weekly-seasonal x SES (pure Python) | Demand | Used. **LightGBM/ETS/Prophet from the proposal were not used** |
| API layer | none (gate is a Python class) | Writes | **FastAPI from the proposal was not built**; RBAC is enforced in `gate.py` |
| LLM | Anthropic Messages API via `urllib` (optional) | Rationale text, text-to-SQL, single-agent baseline | Code present, unexercised |
| Testing | pytest | `project/tests` | Used |

## AI models, services, and development tools disclosure
| Provider | Model / service / tool | Purpose | Where used |
|---|---|---|---|
| OpenAI | ChatGPT (GPT-6) | AI-assisted repository scaffolding and initial documentation drafting | Repository setup and documentation |
| Anthropic | Claude Code (Claude Sonnet 5.5) | AI coding assistant that wrote the `project/` implementation, tests and these docs | Development of this repository |
| Anthropic | Messages API (model set via `LLM_MODEL`) | Optional runtime LLM | **Not used for any reported result**; offline mode only |

## Third-party components and licenses
| Component | Version | License / terms | Purpose |
|---|---|---|---|
| Python | 3.10+ | PSF License | Runtime |
| Pydantic | >=2.5 | MIT | Typed models |
| pytest | >=8.0 | MIT | Tests |

## Benchmarking and evaluation
- **Conditions:** A multi-agent, B single-agent (LLM), C human, D rule-based floor. Only A and D were run.
- **Scenarios:** each seed generates a 40-SKU ERP; every SKU raising a Stock Monitor alert is a case (about 30-35 per seed, 5 seeds). Each system's POs are approved by a *simulated* approver and replayed for 21 days against hidden true demand with seeded supplier delays (same random delays for all systems).
- **Metrics:** unmet-demand rate, expiry write-off value (includes stock already near expiry), overstock value (end stock above 14 days of demand), PO accuracy (same supplier and quantity within 25% of an oracle that uses true future demand), latency, tokens/cost, escalation rate.
- **Reproduce:** `python project/main.py bench` (roughly 15 s). Output goes to `project/results/benchmark.json` and `extra.json`; nothing is hand-edited.
- **Deviations from the proposal:** the replay window is 21 days, not 90, because each decision only covers lead time plus review period. This was changed after a first run with a 28-day window (multi-agent unmet 0.56 vs rule-based 0.44, same ordering of systems as now). There is one repeat per scenario, because offline runs are deterministic (3+ repeats apply once an LLM is used). The human comparison and single-agent baseline were not run.

### Results (run 2026-11-21, seeds 1-5, 40 SKUs, budget cap 250,000, no LLM configured)
| System | Unmet-demand rate | Expiry write-off value | Overstock value | PO accuracy vs oracle | Median latency/case |
|---|---|---|---|---|---|
| A. Multi-agent (deterministic mode) | 0.431 | 48,569 | 0.0 | 0.688 | 6.2 ms |
| D. Rule-based floor | 0.310 | 93,675 | 8.9 | 0.087 | 3.7 ms |
| B. Single-agent LLM | not run | | | | |
| C. Human purchasers | not run | | | | |

Paired difference A minus D across seeds, mean [95% bootstrap CI over 5 seeds]: unmet-demand rate +0.121 [+0.086, +0.166]; expiry write-off -45,106 [-60,678, -31,482]; PO accuracy +0.601 [+0.505, +0.703].

**Reading:** the multi-agent pipeline wrote off about half as much expired stock and matched the oracle PO far more often, but it left *more* demand unmet than the rule-based floor, which simply orders more. That is a real trade-off, not a win on every metric. No LLM ran, so these numbers say nothing about LLM value-add; "multi-agent" here means the deterministic agent pipeline.

Other results:
- Forecast WAPE on a 28-day holdout (60 SKUs): ours 0.207, naive 0.345, seasonal-naive 0.276.
- Safety suite: 5 write-without-approval attempts, 0 succeeded (unsafe-action rate 0.0). Budget cap respected, idempotent retry, append-only audit, rollback, viewer denial, forecaster-failure fallback, injection note flagged, corrupted history flagged: all pass.
- Natural-language queries: 50 questions; execution accuracy 0.933 on the 45 normal ones (offline template translator; the set includes vague phrasings it misses); 5/5 write requests blocked.
- Scalability (cases capped at 100; no LLM so 0 tokens and 0 USD): median latency 4.2 / 4.3 / 5.4 ms at 50 / 500 / 5,000 SKUs.

### Limitations and threats to validity
Synthetic data and simulated suppliers. The oracle reference policy is our own construction and favours forecast-based ordering. The rule-based floor is simple and untuned. Each SKU gets one decision rather than a rolling policy. The query set was written by the same authors as the translator, so 93% is optimistic. Overstock is near zero in this window, so it is uninformative. Five seeds is a small sample. No LLM result exists, so claims about LLM or multi-agent benefit are untested.

## Security, privacy, and ethics
- Secrets only in environment variables (`.env`, git-ignored); none committed.
- Synthetic data only, no personal data.
- Agents hold only read-only DB connections; the single write path is `gate.py`.
- Bias: ranking weights are visible and adjustable. With the default weights the cheap, unreliable supplier is often ranked first, which is a trade-off to review. Per-supplier recommendation frequency is actively tracked in benchmark evaluations and presented in the Streamlit dashboard to audit fairness.
- Prompt injection: supplier notes are screened with a pattern match (basic, bypassable) and never executed as instructions.
