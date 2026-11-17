# Ralypto — Innodata AI Catalyst '26

**University Track · University of Kelaniya**

This repository contains the Ralypto team's submission for **Innodata AI Catalyst '26**. The project will address a real-world challenge through a multi-agent AI system and will include a reproducible comparison with a single-agent baseline and human performance.

> **Project status:** Repository initialized. Problem definition, architecture, and implementation details will be documented as the team finalizes its proposal.

## Repository structure

```text
ralypto-university/
├── project/
│   ├── main.py
│   └── requirements.txt
├── docs/
│   ├── Proposal.docx
│   ├── Workflow.md
│   └── PROJECT_DETAILS.md
├── README.md
├── .gitignore
└── .env.example
```

## Getting started

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

   Windows PowerShell:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   macOS / Linux:
   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r project/requirements.txt
   ```

4. Copy `.env.example` to `.env` and fill in the required values locally. Never commit secrets.

5. Run the application:
   ```bash
   python project/main.py
   ```

## Documentation

- [Project workflow](docs/Workflow.md)
- [Project details and disclosure register](docs/PROJECT_DETAILS.md)
- [Project proposal](docs/Proposal.docx) — to be added before submission

## Evaluation and evidence

The team will document:
- Multi-agent execution traces and agent-to-agent information exchange.
- A fair single-agent baseline performing the same tasks.
- Human baseline methodology.
- Output quality, completion time, and cost under stated test conditions.
- Test scenarios, limitations, and reproducible results.

Benchmark results will only be reported after they are produced by the submitted solution. No results will be fabricated or manually altered.

## Team

**Ralypto**  
University of Kelaniya · Innodata AI Catalyst '26 · University Track

## Competition and integrity

Third-party libraries, models, APIs, and AI development tools will be acknowledged in `docs/PROJECT_DETAILS.md`. Any confidential competition material will be handled according to the organizer's rules. API keys, access tokens, passwords, and private data must never be committed to this repository.

---

*Solve Today, Build Tomorrow.*
