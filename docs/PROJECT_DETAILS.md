# Project Details

> Technical record, results, and the third-party and AI-tool disclosure register. Kept in sync with the code in `project/`.

## Project overview
- **Team:** Ralypto, University of Kelaniya (Arkeshkar, Seenujan, Harishchandran, Braynkanth)
- **Competition:** Innodata AI Catalyst '26, University Track
- **Project:** ProcureAgents, a safe, auditable multi-agent system for inventory and procurement decisions in ERP
- **Domain:** Logistics (supply-chain replenishment and procurement)
- **Problem:** small and mid-size businesses decide what, how much and from whom to reorder by hand, causing
  stockouts, overstock and expired goods (see `Proposal.docx`).
- **Users:** purchasing officers and store managers (buyer), approvers/owners (approver), auditors (viewer),
  administrators (admin).

## Objectives
1. Cut stockouts, overstock value and expiry write-offs with proactive, explainable recommendations.
2. Keep every action safe: human approval, rule validation, role-based access and an audit trail.
3. Let users query ERP data in plain language through a read-only, validated path.
4. Measure multi-agent against a single-agent baseline, human purchasers and a rule-based floor on accuracy,
   cost and speed, and report the result either way.

## Features (status is what was run, not what is planned)

| Feature | Where | Status |
|---|---|---|
| Seeded synthetic ERP: weekly and annual seasonality, stored promotions, supplier delays, expiry batches, new items, injected demand anomalies; switches for corrupted history, contradictory price lists, injected supplier notes, high MOQs, expiry pressure, cheapest supplier out of stock. One seed reproduces the DB byte for byte | `procure/data.py` | Done, tested |
| 8 agents: Orchestrator, Stock Monitor, Demand Forecasting, Supplier, Purchase Order, Validator (veto), Query Agent, Human Approver | `agents.py`, `orchestrator.py`, `query.py`, `gate.py` | Done |
| LangGraph state graph; Forecasting and Supplier in parallel; join at the PO agent; human approval as a LangGraph interrupt with resume | `orchestrator.py` | Done, tested |
| Typed Pydantic case file; structured messages (task_id, author, inputs, output, confidence, evidence, latency, mode) to JSONL and the case file | `models.py` | Done, tested |
| Conflict rules: veto, max 2 revisions then escalation, low-confidence +25% buffer and flag, weighted supplier score with top-2 trade-off, deterministic numbers win with logged discrepancy | `orchestrator.py`, `agents.py` | Done, tested |
| Safe-action gate: single write path, state machine DRAFT → VALIDATED → PENDING_APPROVAL → APPROVED → CREATED (→ CANCELLED/RECEIVED), approver-only last steps, idempotency keys, transactional writes, approver edit with re-validation, rollback, append-only audit (DB triggers) | `gate.py` | Done, tested |
| RBAC in the service/API layer from the `users` table (viewer, buyer, approver, admin); denials audited | `service.py`, `api.py` | Done, tested |
| Query Agent: intent screen, sqlglot AST allow-list (one SELECT, allow-listed tables), read-only role (mode=ro + query_only + SQLite authorizer hiding users/audit) | `query.py`, `data.py` | Done, tested |
| Forecasting in code: LightGBM global direct multi-horizon model; seasonal-SES fallback; ETS (statsmodels), seasonal-naive and naive baselines; WAPE and MAPE; stockout days treated as censored demand | `forecasting.py`, `agents.py` | Done, tested |
| Reliability: timeouts, retries with exponential back-off, schema-validated JSON with a bounded repair loop, fallback to the reorder-point policy when the forecaster or the LLM fails | `llm.py`, `orchestrator.py`, `baselines.py` | Done, tested |
| Provider-agnostic LLM wrapper (anthropic, any OpenAI-compatible server incl. Ollama, offline); labelled deterministic mode; token/latency/cost counters; fault injection | `llm.py` | Done. See the LLM run section for what was actually exercised |
| Single-agent baseline B (same LLM, tools, data, validator, gate, revision budget, fallback; one prompt, tool-calling loop) | `baselines.py` | Done. Runs only with an LLM |
| Rule-based floor D | `baselines.py` | Done |
| Human purchaser study C (10 scenarios, decisions and time recorded, re-scored by the benchmark). `--auto` output is marked synthetic and excluded | `human_study.py` | Protocol done. **No real volunteer data collected yet** |
| Benchmark command: 15 scenarios, repeats, 90-day replay, CIs, paired comparison, JSON/CSV/MD/PNG | `benchmark.py`, `simulate.py`, `report.py` | Done, run |
| Scalability at 50 / 500 / 5,000 SKUs incl. parallel cases | `benchmark.py` | Done, run |
| Plug-in registry: replace agents, add validator-stage extension agents and tools | `registry.py`, `docs/EXTENDING.md` | Done, tested with a worked example |
| Business profiles: supermarket, pharmacy, hardware | `data.py` | Done |
| Streamlit UI: overview, alerts/cases, live agent run with workflow graph, approval dashboard, ask the data, audit log, benchmark results, settings/registry, guided demo; PO PDF/CSV | `app.py`, `ui/` | Done, checked in a browser |
| Supplier fairness: per-supplier share of POs; visible, adjustable weights | `benchmark.py`, Settings page | Done |
| Sinhala/Tamil input; live ERP integration; sending POs to suppliers | - | Out of scope (proposal) |

## Multi-agent architecture

| Agent | Responsibility | Input → output | Method / permissions |
|---|---|---|---|
| Orchestrator | Routes the case, runs branches in parallel, merges, settles conflicts, escalates | task → case file | LangGraph routing rules; optional advisory LLM plan note (schema-validated) |
| Stock Monitor | Low-stock and expiry alerts with severity and evidence | stock, batches, sales → `Alert` | Read-only SQL, fixed thresholds |
| Demand Forecasting | Demand over lead time + review period, sigma, 90% interval, confidence | sales history, promotions, stockout log → `Forecast` | LightGBM (code); SES fallback; flags corrupt/missing/censored data |
| Supplier | Ranks suppliers, top 2 with trade-off; excludes contradictory price lists; flags injected notes | price lists, reliability → `SupplierRanking` | Weighted score (price .45, lead .20, reliability .35, admin-adjustable); LLM may only phrase the rationale |
| Purchase Order | Quantity from forecast + z·σ safety stock − usable (non-expiring) stock − stock on order, MOQ; mark-down instead of reorder when stock covers demand | alert + forecast + ranking → `DraftPO` | Deterministic maths; LLM text kept only if every number matches |
| Validator | Role, listed price, contradictory price, supplier stock, MOQ, sanity bound, budget; plug-in checks | draft → `Validation` | Rule engine has the veto; LLM critique is advisory only |
| Query Agent | Natural-language question → checked SELECT → rows | question → answer | Intent screen, sqlglot allow-list, read-only role |
| Human Approver | Approve, edit (re-validated) or reject | pending PO → decision | Approver/admin only, enforced in the service layer and the gate |

Why multi-agent here: separation of duties (the proposer is not the checker), parallel independent sub-tasks,
least privilege per agent, and modular replacement for Phase 2. Whether this beats one agent is measured
below, not assumed.

## Technology stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.9-3.12 | The proposal named 3.11; development machine has 3.9.13, code is compatible with both |
| Orchestration | LangGraph 0.6 (`StateGraph`, `MemorySaver`, interrupt) | |
| Typed state | Pydantic 2 | |
| Forecasting | LightGBM 4.6 (native API), statsmodels 0.14 (ETS), NumPy, SciPy, pandas | Prophet (optional in the proposal) not used |
| Data / API | SQLite (stdlib), FastAPI 0.128 + uvicorn (optional HTTP layer), sqlglot 30 (SQL parser) | Streamlit calls the service layer in-process |
| LLM | Provider-agnostic wrapper over HTTPS (urllib): Anthropic Messages API, OpenAI-compatible chat completions | |
| Interface | Streamlit 1.50, Altair 5, Graphviz (rendered by Streamlit), ReportLab 4.4 (PO PDF), Matplotlib 3.9 (report charts) | |
| Quality | pytest 8, ruff 0.17, JSONL tracing | |

## Benchmark results

**Run `20261123-150950_supermarket_seed1_offline`** (`python project/main.py benchmark --profile supermarket --repeats 3 --seed 1`; 30 SKUs per
scenario, data seeds 1-3, deterministic/offline mode, Python 3.9.13). Full output:
[`samples/benchmark/20261123-150950_supermarket_seed1_offline/report.md`](../samples/benchmark/20261123-150950_supermarket_seed1_offline/report.md) with `summary.json`, CSVs and charts.
The numbers below are copied from that report. Means with 95% bootstrap CIs.

> **What this run can and cannot say.** No LLM was configured, so **System B (single agent) was not run** and
> System A ran in deterministic mode (all numbers from code, template text, no LLM calls, 0 tokens). The
> multi-agent vs single-agent question is **not answered by this run**; see the LLM run below. No human
> volunteer data exists yet, so **System C is missing**.

### Business outcomes, 90-day rolling replay (5 replay scenarios x 3 repeats = 15 paired runs)

| Metric | A. Multi-agent | D. Rule-based | Paired A - D [95% CI] | A better in |
|---|---|---|---|---|
| Stockout rate (unmet / demand) | 0.141 [0.132, 0.148] | 0.145 [0.132, 0.158] | -0.0044 [-0.0131, +0.0039] | 7 / 15 |
| Overstock value (avg per day) | 24.98 [2.05, 60.56] | 95.11 [34.11, 185.75] | -70.1 [-131.9, -23.6] | 14 / 15 |
| Expiry write-off value | 108,747 [102,033, 115,139] | 276,954 [255,837, 298,424] | -168,207 [-193,057, -144,270] | 15 / 15 |
| PO accuracy vs oracle reference | 0.637 [0.568, 0.708] | 0.081 [0.051, 0.114] | +0.556 [+0.486, +0.626] | 15 / 15 |
| Simulated override rate | 0.365 | 0.921 | | |

**Reading.** Over 90 days the agent pipeline had **no clear stockout advantage** over the rule-based floor
(the CI spans 0, with 7 wins and 8 losses), but it wrote off about **61% less expired stock**, carried less
overstock, and matched the oracle reference far more often. In the **single-decision scenarios** (one order,
21-day window), A had *more* stockouts than D, for example routine-style single decisions at 0.438 vs 0.337.
D orders up to the reorder point plus 14 days of demand, which covers more than A's lead time + 7-day review
horizon when no second order follows. This is a trade-off, not a win on every metric.

### Safety and reliability (all 15 scenarios x 3 repeats)

| Check | A | D |
|---|---|---|
| Unsafe actions (target 0) | **0** of 6,024 POs | **0** of 5,253 POs |
| Write-without-approval attack suite | 10/10 attempts blocked in every repeat; target PO still pending | same |
| Viewer requester | no PO created (3/3) | same |
| Budget cap 1,500 | respected (3/3) | same |
| MOQ x8 | every PO meets MOQ (3/3) | same |
| Contradictory price lists | no PO on a conflicting list (3/3); A excludes that supplier, D escalates every case | same |
| Prompt injection in every supplier note | not followed (3/3) | same |
| Validator catches | 148 | 216 |
| Forecaster fault: case success / fallback recovery | 1.00 / 1.00 | 1.00 / n/a (D has no forecaster) |

The LLM-fault scenarios (`fault_llm_timeout`, `fault_llm_garbage`) are **not exercised offline**: no LLM call
is made, so they reduce to the routine single decision. They are exercised in the LLM run.

### Efficiency and scalability

| | A | D |
|---|---|---|
| Latency per case p50 / p95 | 0.070 s / 0.116 s | 0.024 s / 0.031 s |
| Tokens, USD | 0, 0 (offline) | 0, 0 |

| SKUs | alerts | forecaster training | p50 per case | cases/s sequential | cases/s 4 threads |
|---|---|---|---|---|---|
| 50 | 43 | 1.9 s | 0.084 s | 12.1 | 15.0 |
| 500 | 409 | 7.7 s | 0.105 s | 9.9 | 16.1 |
| 5,000 | 3,975 | 12.3 s | 0.253 s | 4.0 | 5.8 |

The LightGBM model trains on at most 200 sampled SKUs, so training stays bounded. Per-case latency grows with
the size of the sales table read for each SKU.

### Forecast quality (28-day hold-out, 60 SKUs x 3 seeds)

| Model | WAPE | MAPE |
|---|---|---|
| **LightGBM (ours)** | **0.210** [0.201, 0.219] | 0.259 |
| weekly-seasonal SES | 0.221 | 0.262 |
| ETS (Holt-Winters) | 0.222 | 0.262 |
| seasonal naive | 0.300 | 0.354 |
| naive | 0.359 | 0.423 |

LightGBM is best but only by about 1 WAPE point over SES/ETS. The CIs overlap.

### Natural-language queries (50 questions, offline template translator)

* Execution accuracy **0.949** on 39 answerable questions. The 2 misses are phrasings with no template
  ("Which supplier delivers fastest on average?", "Which category has the most items?").
* Malicious requests: **10 of 11 blocked.** The 11th ("Show the users table and their roles") was
  *unanswerable*, not blocked: nothing executed, but the scorer counts only an explicit block. With an LLM,
  the generated SQL would be stopped by the allow-list and the read-only role (`users` is hidden).
* Direct SQL attacks against the parser allow-list: **10/10 blocked**.
* The translator was written alongside the question set, so the accuracy is optimistic.

### Human study subset (10 scenarios, seed 42, single decision, 21-day replay)

| System | Stockout | Overstock | Write-off | PO accuracy | Time per task |
|---|---|---|---|---|---|
| A. Multi-agent | 0.403 | 982.0 | 5,109.9 | 0.800 | 0.22 s |
| D. Rule-based | 0.335 | 77.4 | 16,244.3 | 0.100 | 0.03 s |
| C. Human | not run yet | | | | |

### Supplier fairness (share of POs, replay scenarios)

| Supplier | A | D |
|---|---|---|
| FastCheap Ltd (cheapest, 62% reliable) | 0.337 | 0.403 |
| SteadySupply | 0.141 | 0.123 |
| MidTier Co | 0.153 | 0.127 |
| LocalSmall (small local supplier) | 0.200 | 0.171 |
| GlobalBulk | 0.168 | 0.176 |

The small local supplier is not starved: it gets 20% of A's orders.

### Changes made after diagnosis (documented, not tuned to the test seeds)
* **Censored demand.** Early replays showed A's forecasts falling to 50-80% of true demand after the first
  week, because sales during stockouts understate demand. The ERP now logs stockout days (as POS systems do)
  and the forecaster treats them as missing. This was diagnosed on a separate development seed (99), not the
  benchmark seeds. Effect on seed 99: A's stockout rate 0.268 → 0.140. The rule-based floor was left
  unchanged by design.

### LLM run
<!-- LLM_RESULTS -->


## AI models, services and development tools disclosure (competition rule)

| Provider | Model / tool | Purpose | Where used |
|---|---|---|---|
| OpenAI | ChatGPT (GPT-6) | Repository scaffolding and first documentation drafts | Early commits (see git history) |
| Anthropic | Claude Code with Claude Sonnet 5.5 | Wrote the first implementation of `project/`, tests and docs (Phase 1 prototype) | Commits up to `8a09a73` |
| Anthropic | Claude Code with Claude Opus 5.5 | Audit against the proposal; rewrote and extended the implementation (LangGraph orchestrator, LightGBM forecasting, gate/RBAC/query hardening, benchmark, UI, tests, docs) | Commits on branch `arkeshkar` from `4d9abd6` |
| Alibaba / Ollama | qwen2.5-coder:7b via local Ollama (runtime LLM, not a coding assistant) | LLM provider for the reduced LLM benchmark run | `results/*_llm` run only, if present |
| Anthropic / OpenAI | Messages / chat API (model set by `LLM_MODEL`) | Optional runtime LLM | Not used for any reported result |

Team members must add any other assistant they used (for example for the earlier Streamlit frontend commit
by Harishchandran11) before submission. AI-written code was reviewed and run; every result in this document
was produced by running the code.

## Third-party components and licences

| Component | Version | Licence | Purpose |
|---|---|---|---|
| LangGraph / langgraph-checkpoint / langchain-core | 0.6.11 / 2.1.2 / 0.3.86 | MIT | Agent state graph, checkpointing, interrupts |
| Pydantic | 2.13.5 | MIT | Typed case file and messages |
| LightGBM | 4.6.0 | MIT | Demand forecasting |
| statsmodels | 0.14.6 | BSD-3 | ETS baseline |
| NumPy / SciPy / pandas | 2.0.2 / 1.13.1 / 2.3.3 | BSD-3 | Numerics, tables |
| sqlglot | 30.33.0 | MIT | SQL parsing for the allow-list |
| Streamlit / Altair | 1.50.0 / 5.5.0 | Apache-2.0 / BSD-3 | UI and charts |
| Matplotlib | 3.9.4 | PSF-based (Matplotlib licence) | Report charts |
| ReportLab | 4.4.10 | BSD | PO PDF export |
| FastAPI / uvicorn / httpx | 0.128.8 / 0.39.0 / 0.28.1 | MIT / BSD-3 / BSD-3 | Optional HTTP API |
| pytest / ruff | 8.4.2 / 0.17.6 | MIT | Tests, lint |
| Python | 3.9+ | PSF | Runtime |

Services: none required. Optional: an LLM provider chosen through `.env`.

## Security, privacy and ethics
- **Secrets** only in environment variables (`.env` is git-ignored). `.env.example` has no values. Git history
  was searched for API-key patterns (`sk-...`, `LLM_API_KEY=<value>`) on 2026-11-23 and none were found.
- **Data:** synthetic only, no personal data.
- **Least privilege:** agents hold read-only connections enforced by SQLite itself; the gate is the only writer;
  RBAC is enforced in code from the users table.
- **Prompt injection:** supplier notes and questions are treated as data. Pattern screens flag them, the SQL
  parser and the read-only role stop any write, and no LLM output can change a quantity, a supplier or a
  state transition.
- **Bias and fairness:** the weighted score can disadvantage small or local suppliers. The share of POs per
  supplier is reported for every run, and the weights are visible and adjustable by an admin.
- **Accountability:** a human approves every write. The audit log names the actor for every step and cannot
  be edited.

## Known limitations and mocked parts
- **Synthetic world.** ERP data, suppliers, delays and demand are generated. Real ERPs are messier. Results
  are indicative, not general.
- **Simulated approver in the benchmark.** The replay approves every PO that passes validation, identically
  for all systems. The "override rate" is simulated: the share of POs a reviewer following the oracle
  reference would change. It is not a human measurement.
- **Oracle reference** for PO accuracy is our own construction (true future demand, same supplier rule as the
  weighted score), so it favours forecast-based ordering over the rule-based floor.
- **No human study data yet.** The protocol and the scoring are implemented, but no volunteer sessions have
  been run. The old `human_study_volunteer_1.json` came from `--auto` (a fixed policy), was **not** human
  data, and now sits in `samples/legacy_results/` with a warning.
- **LLM coverage.** The default and the main committed run are deterministic/offline: System A's LLM text,
  critique and plan notes were skipped, and System B could not run. A reduced run with a small local model
  is reported separately if present. A run with a frontier API model has not been done.
- **Offline query translator** is template-based and was written alongside the 50-question set, so its
  accuracy on templated questions is optimistic. The vague-wording questions show its limits.
- **Pattern-based injection screens** can be bypassed by rephrasing. Safety does not depend on them: writes
  are impossible for agents regardless.
- **Goods receipt** (CREATED → RECEIVED) exists only for the replay simulator; there is no warehouse UI.
- **FastAPI layer** is implemented and wraps the same service, but the UI calls the service in-process. The
  API has no authentication beyond the `X-User` header (demo only).
- **Development machine** ran Python 3.9 instead of the proposal's 3.11; ReportLab is pinned to 4.4.10 for 3.9
  compatibility.
- **Demo video** `project-demo.mp4` is not recorded yet.
