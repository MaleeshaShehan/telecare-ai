# TeleCare AI

An agentic tier-1 customer-care system for a telecom operator. Four FastAPI agents
talk over HTTP with a shared JSON envelope; a Streamlit UI sits on top.

SLIIT IT 3041 (Information Retrieval and Web Analytics) group project.
Full plan: [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md).

## Agents

| Agent | Port | Role |
| --- | --- | --- |
| Orchestrator | 8000 | Entry point. Sanitise, NLU, auth gate, route, compose. |
| Knowledge Agent | 8001 | RAG over the telecom corpus with citations. |
| Account Agent | 8002 | Login/OTP/JWT and read-only bill and quota lookups. |
| Supervisor Agent | 8003 | Sentiment assessment and escalation to tickets. |
| Web UI | 8000 (`/`) | Static single-page app in `ui/web`, served by the Orchestrator. Chat, login with simulated-SMS OTP, live agent trace, agent console. |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m spacy download en_core_web_sm
copy .env.example .env            # then fill in the keys
python data/db/seed.py                      # build synthetic DBs
python -m agents.knowledge_agent.ingest     # build Chroma + BM25 indexes
python run_all.py                           # start 4 agents, opens http://127.0.0.1:8000/
```

If `INTERNAL_API_KEY` is blank or still set to the development default,
`run_all.py` generates one temporary key and shares it with all four agent
processes. The value is neither printed nor written to disk.

The UI is plain HTML, CSS and JavaScript with no build step. Edit the files in
`ui/web` and refresh the browser.

## Working on one agent

Each specialist has a builder guide: [`agents/knowledge_agent/README.md`](agents/knowledge_agent/README.md),
[`agents/account_agent/README.md`](agents/account_agent/README.md),
[`agents/supervisor_agent/README.md`](agents/supervisor_agent/README.md). The Orchestrator is documented in
[`agents/orchestrator/README.md`](agents/orchestrator/README.md).

```bash
python -m agents.knowledge_agent                      # run only your agent, auto-reload
python scripts/ping_agent.py knowledge_agent --intent package_info --query "cheapest 5GB"   # test it alone
set LLM_PROVIDER=mock && pytest tests/contract -q     # your definition of done
```

## Tests

```bash
set LLM_PROVIDER=mock && pytest -q          # Windows
LLM_PROVIDER=mock pytest -q                 # macOS/Linux
```

## Contributors

| Member | Owns |
| --- | --- |
| M1 (lead) | Orchestrator, `shared/` (contracts, LLM client, security helpers), web UI, run_all.py, ping script, contract tests, intent eval, integration |
| M2 | Knowledge Agent end to end: corpus, ingest, retrieval, generation, IR evaluation |
| M3 | Account Agent end to end: schema and seed, login/OTP/JWT, read-only repository, bill diff, security test log |
| M4 | Supervisor Agent end to end: sentiment, summariser, tickets, console data; Responsible AI doc, commercialisation section, video |

All data is synthetic. No real customer data anywhere.

## Known limitations (stated on purpose)

- Sessions are in memory and keyed by a browser-generated conversation id. A restart logs everyone out. Production would use Redis and a server-issued session cookie.
- The prompt-injection filter is a phrase list plus sanitisation. It blocks known strings, not paraphrases.
- Rate limiting is per conversation id with a per-IP backstop. A new conversation id resets the first counter.
- Plan advice is recommendation by retrieval over package descriptions, not a cost calculation against measured usage.
- English only. Sinhala and Tamil are future work.
- Agents talk over plain HTTP on localhost. Production would use TLS and a service mesh.
