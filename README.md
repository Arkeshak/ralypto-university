# Ralypto — Innodata AI Catalyst '26

**University Track · University of Kelaniya**

This repository contains the Ralypto team's submission for **Innodata AI Catalyst '26**. The project addresses a real-world challenge through a multi-agent AI system, with a reproducible comparison against a single-agent baseline and human performance.

## Required Project Structure

```text
ralypto-university/
├── project/
│   ├── main.py
│   ├── requirements.txt
│   ├── procure/        (agents, gate, orchestrator, evaluation)
│   ├── tests/
│   └── results/        (generated benchmark output and traces)
├── README.md
├── docs/
│   ├── Proposal.docx
│   ├── Workflow.md
│   └── PROJECT_DETAILS.md
└── project-demo.mp4
```

## File Descriptions

| File / Folder | Description |
|---|---|
| `main.py` | Main application entry point. |
| `requirements.txt` | Python dependencies required to run the project. |
| `README.md` | Project overview, setup instructions, and execution guide. |
| `docs/Proposal.docx` | Project proposal describing the problem, the solution, and the planned implementation. |
| `docs/Workflow.md` | Project workflow, process flow, and implementation steps. |
| `docs/PROJECT_DETAILS.md` | Project objectives, features, functionality, and technical details. |
| `project-demo.mp4` | Project demonstration video. |

## Getting Started

### Requirements

- Python 3.10 or later
- pip

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Arkeshak/ralypto-university.git
   cd ralypto-university
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   ```

   **Windows PowerShell:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   **macOS / Linux:**
   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r project/requirements.txt
   ```

4. Copy `.env.example` to `.env` and fill in the required values. Never commit secrets.

### Execution

```bash
python project/main.py demo            # seed a synthetic ERP, run agents, approve one PO
python project/main.py ask "Which items expire next month?"
python project/main.py approve 3       # approve a pending PO as user bob (approver)
python project/main.py bench           # full evaluation, writes project/results/
python -m pytest project/tests -q
```

Runs fully offline by default. To enable optional LLM text (rationales, text-to-SQL, single-agent baseline), set `LLM_PROVIDER=anthropic`, `LLM_MODEL` and `LLM_API_KEY` in `.env`. The LLM path has not been exercised against a live API yet.

### Status

Phase 1 prototype implemented in deterministic mode. Not yet built: Streamlit UI, FastAPI layer, LangGraph, LightGBM, human baseline, live-LLM runs. See `docs/PROJECT_DETAILS.md` for results and limitations.

## Documentation

- [Project Proposal](docs/Proposal.docx)
- [Project Workflow](docs/Workflow.md)
- [Project Details](docs/PROJECT_DETAILS.md)

## Team

**Ralypto**  
University of Kelaniya · Innodata AI Catalyst '26 · University Track

---

*Solve Today, Build Tomorrow.*
