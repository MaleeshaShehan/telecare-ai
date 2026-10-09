# TeleCare AI — instructions for Claude Code

University project (SLIIT IT 3041, Information Retrieval and Web Analytics). A 4-agent
tier-1 customer-care system for a telecom operator. Full plan: `docs/BUILD_PLAN.md`.
Read it before starting any new component.

## Architecture (do not change without the team agreeing)

- 4 FastAPI services + a static web UI, one monorepo.
  - `agents/orchestrator` :8000 — the only service the UI calls (`POST /chat`); also
    serves the UI from `ui/web/` at `/`
  - `agents/knowledge_agent` :8001 — RAG over `data/corpus` (the IR module)
  - `agents/account_agent` :8002 — bills/quota for one logged-in subscriber; owns login/OTP/JWT
  - `agents/supervisor_agent` :8003 — sentiment (assess) and escalation to tickets
  - `ui/web/` — plain HTML/CSS/JS single-page app (no framework, no build step).
    Decided 8 Oct 2026, replacing Streamlit. The browser never receives a JWT.
- Specialists never call each other. Everything goes through the orchestrator.
- Agents talk with the `Envelope` model in `shared/envelope.py` (8 fields:
  message_id, conversation_id, sender_agent, receiver_agent, intent, payload,
  auth_token, timestamp). Replies put `status` + results in `payload`.
  Status values: ok | needs_auth | forbidden | not_found | escalate | error.
- Every specialist endpoint requires the `X-Internal-Key` header (from `.env`).
- Agent communication is API-based (HTTP + JSON envelope). We do NOT use MCP.

## Hard rules

- Account Agent is read-only at runtime and can prove it with a failed write. SQLite:
  `sqlite3.connect("file:data/db/telecare.db?mode=ro", uri=True)`. Supabase/Postgres:
  a SELECT-only role for the agent's connection. OTP hashes go in a separate writable
  store (`auth.db` or a table). Each builder chooses SQLite or Supabase; tests must
  pass offline either way.
- Login is passwordless: a known mobile number requests a backend-generated SMS OTP.
  OTPs are hashed, expire after five minutes, allow three attempts, and are single-use.
- The subscriber ID always comes from the verified JWT, never from message text.
- An authenticated account request that explicitly names a different or malformed mobile number is denied before account data is read.
- All SQL is parameterised (`?`). No string-built SQL anywhere.
- Bill numbers are computed in Python (`bill_diff.py`); the LLM only phrases them.
- Every outgoing LLM prompt goes through `shared/llm.py`, which masks PII.
- The Knowledge Agent answers only from retrieved chunks, cites sources as [1], [2],
  and returns `not_found` when evidence is weak. Never answer from model memory.
- All data is synthetic. Never add real customer data.
- No secrets in code or Git. Everything configurable lives in `.env`.
- Out of scope: account changes/writes, plan cost-optimizer, real telco APIs,
  WhatsApp, Sinhala/Tamil. Do not add these.

## Stack

Python 3.11 · FastAPI + uvicorn · Pydantic · httpx · Gemini (primary) / GPT via OpenAI (backup)
via `shared/llm.py` · sentence-transformers `all-MiniLM-L6-v2` · ChromaDB · rank_bm25 ·
spaCy `en_core_web_sm` · vaderSentiment · SQLite · bcrypt · PyJWT · cryptography (Fernet)
· slowapi · Faker · pytest. UI: vanilla HTML/CSS/JS served by FastAPI StaticFiles.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python data/db/seed.py                               # build synthetic DBs
python -m agents.knowledge_agent.ingest              # build Chroma + BM25 indexes
python run_all.py                                    # start 4 agents; UI at http://127.0.0.1:8000/
LLM_PROVIDER=mock pytest -q                          # tests never call real LLMs
python eval/run_ir_eval.py                           # P@3, Recall@5, MRR
python eval/run_intent_eval.py                       # intent accuracy + confusion matrix
```

Corpus documents go in `data/corpus/raw/`, one row each in `data/corpus/manifest.csv`.
Course briefs and the viva cram sheet are in `docs/brief/`.

## How to work in this repo

- One builder per specialist, end to end. Each agent folder has a `README.md` builder
  guide with the contract, examples, build order and definition of done. Builders do
  not edit `shared/`, `agents/orchestrator/`, `ui/`, other agents, or `tests/contract/`.
- Run one agent alone with `python -m agents.<agent>`; test it alone with
  `python scripts/ping_agent.py <agent> …`; prove the contract with `pytest tests/contract/`.
- `LLM_PROVIDER=mock pytest -q` must pass with no internet and no API keys, whatever
  data store or SMS channel a builder chooses.
- Build in small, testable slices. Each agent must run and be tested on its own.
- Write or update a pytest for every change; run tests with `LLM_PROVIDER=mock`.
- Keep code simple and commented. Every team member must be able to explain
  every line at the viva — prefer plain Python over frameworks (no LangChain/CrewAI).
- Log every agent decision to the audit log (`shared/audit.py`): decision + reason,
  never raw message text.
- Ask before changing anything in `shared/` — other members depend on it.
