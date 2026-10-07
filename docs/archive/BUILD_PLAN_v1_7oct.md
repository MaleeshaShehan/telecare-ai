# TeleCare AI — System Build Plan

As of 7 Oct 2026 · IT 3041 group project

> **Amendment 8 Oct 2026 (UI).** The Streamlit UI is replaced by a static single-page
> app in `ui/web/` (plain HTML, CSS, JS, no build step) served by the Orchestrator at
> `http://127.0.0.1:8000/`. Agents, protocol and ports are unchanged. Wherever this
> document says `ui/app.py`, `:8501` or Streamlit, read `ui/web/` on `:8000`.
> The browser never receives the JWT; the Orchestrator keeps it per conversation.

## 1. Where we are and what we're building

Mid-eval is done, so Weeks 7–10 turn the agreed design into working code. **Done means: the demo story runs end-to-end in the UI, and we have IR evaluation numbers and a security test log for the report.** The design does not change: same 4 agents, same HTTP + JSON envelope, same stack.

| Tier | What we build | Why |
| --- | --- | --- |
| **Must** | 4 FastAPI agents talking via the JSON envelope | ≥2 interacting agents + defined protocol |
| **Must** | RAG over our telecom documents (dense + BM25 hybrid) with citations | IR module, the course's core |
| **Must** | Intent + NER (orchestrator), sentiment + summarization (supervisor) | NLP requirement |
| **Must** | Login + OTP + JWT, bcrypt, parameterized SQL, sanitization, injection filter, PII masking, Fernet | Security requirement |
| **Must** | Synthetic subscriber DB with this + last month's bills; bill-change explanation | Account Agent + demo story |
| **Must** | Escalation to a ticket with reference number | Human-in-the-loop (Responsible AI) |
| **Must** | Streamlit chat UI with sources and an agent-trace panel | Demo, video, viva |
| **Must** | IR eval (P@3, MRR × 3 configs), intent accuracy, security test log | "Evaluation results" in the report |
| Should | Query-rewrite retry loop when retrieval is weak | Stronger "agentic" story |
| Should | Small "human agent console" page listing tickets | Shows the hand-off side |
| Should | docker-compose for one-command start | GitHub marks, easier viva demo |
| Out of scope | Account changes, plan cost-optimizer, real telco APIs, WhatsApp, Sinhala/Tamil, MCP | Documented as future work |

### Engineering decisions locked now

| Decision | Choice | Why |
| --- | --- | --- |
| Repo | One monorepo, one `shared/` package all agents import | One envelope definition, no drift |
| Contracts first | Envelope + intent list merged on day 1–2 | Everyone codes against the same shape |
| Who owns login | Account Agent issues and verifies tokens; orchestrator only proxies | The data owner controls access |
| Read-only claim | Account DB opened with SQLite `mode=ro` | "Read-only" is enforced, not promised |
| Numbers vs words | Bill maths in plain Python; the LLM only phrases the result | No hallucinated amounts |
| LLM calls per turn | 1 for NLU (intent + entities together) + 1 for the answer | Stays inside free-tier limits |
| Sentiment | VADER locally every turn; LLM only for borderline cases | Fast, free, explainable |
| Testing without quota | `LLM_PROVIDER=mock` returns canned replies | Tests and CI never burn API calls |
| Service-to-service | Shared internal key header on every specialist call | Specialists accept calls only from the orchestrator |

## 2. Runtime architecture

Five processes run side by side: four FastAPI agents and the Streamlit UI. `python run_all.py` starts them all with uvicorn and checks each `/health` before opening the UI.

```
                     ┌──────────────────────────────┐
                     │  Streamlit UI  :8501         │
                     │  chat · login + OTP · trace  │
                     └──────────────┬───────────────┘
                                    │ POST /chat
        ┌───────────────────────────▼────────────────────────────┐
        │  Care Orchestrator  :8000                              │
        │  rate limit → sanitize → injection check → NLU → assess│
        │  auth gate → route to ONE specialist → compose + audit │
        └──────┬──────────────────────┬──────────────────────┬───┘
               │   Envelope over HTTP │ (X-Internal-Key)     │
   ┌───────────▼─────────┐ ┌──────────▼──────────┐ ┌─────────▼───────────┐
   │ Knowledge Agent     │ │ Account Agent       │ │ Supervisor Agent    │
   │ :8001               │ │ :8002               │ │ :8003               │
   │ BM25 + dense (RRF)  │ │ login · OTP · JWT   │ │ assess: VADER+rules │
   │ sufficiency → retry │ │ scoped param. SQL   │ │ escalate → ticket   │
   │ cited answer        │ │ bill diff (Python)  │ │ T-1001, T-1002 …    │
   └───────────┬─────────┘ └──────────┬──────────┘ └─────────┬───────────┘
   ┌───────────▼─────────┐ ┌──────────▼──────────┐ ┌─────────▼───────────┐
   │ Chroma + bm25.pkl   │ │ telecare.db (ro)    │ │ tickets.db          │
   │ our telecom corpus  │ │ + auth.db (OTP)     │ │ agent console       │
   └─────────────────────┘ └─────────────────────┘ └─────────────────────┘
   ┌────────────────────────────────────────────────────────────────────┐
   │ shared/ library — imported by all four agents (not a service)      │
   │ LLMClient (Gemini → Groq → mock, PII masked) · security · envelope │
   │ · audit log                                                         │
   └────────────────────────────────────────────────────────────────────┘
```

The UI only ever talks to the orchestrator, and each specialist owns its own store. Specialists never call each other.

## 3. Project structure

```
telecare-ai/
├── CLAUDE.md                 # instructions Claude Code reads every session
├── README.md                 # setup, usage, screenshots, contributors table
├── .env.example              # every variable, no real keys
├── .gitignore                # .env, data/chroma, *.db, __pycache__, .venv
├── requirements.txt
├── run_all.py                # starts the 4 agents + UI in one command
├── docker-compose.yml        # (Should) one-command start
│
├── shared/                   # imported by every agent
│   ├── config.py             # reads .env (ports, keys, model names, thresholds)
│   ├── envelope.py           # Envelope model + make_reply()
│   ├── intents.py            # Intent enum + which agent owns which intent
│   ├── llm.py                # LLMClient: Gemini → Groq fallback → mock
│   ├── security.py           # sanitize, injection check, PII mask, JWT, Fernet
│   ├── http.py               # call_agent(): internal key, timeout, retry
│   └── audit.py              # logs every agent decision to audit.db
│
├── agents/
│   ├── orchestrator/         # port 8000
│   │   ├── main.py           # POST /chat, /auth/login, /auth/verify-otp
│   │   ├── nlu.py            # intent classification + NER
│   │   ├── router.py         # the decision loop
│   │   ├── session.py        # conversation history + token per conversation
│   │   └── composer.py       # final reply, sources, AI disclosure
│   ├── knowledge_agent/      # port 8001
│   │   ├── main.py           # POST /handle
│   │   ├── ingest.py         # load → clean → chunk → embed → index
│   │   ├── retriever.py      # dense, BM25, hybrid (RRF)
│   │   ├── generator.py      # grounded answer + citations
│   │   └── prompts.py
│   ├── account_agent/        # port 8002
│   │   ├── main.py           # POST /handle, /auth/login, /auth/verify-otp
│   │   ├── auth.py           # bcrypt check, OTP, JWT issue/verify
│   │   ├── repository.py     # parameterized SQL only
│   │   ├── bill_diff.py      # this month vs last month, pure Python
│   │   └── prompts.py
│   └── supervisor_agent/     # port 8003
│       ├── main.py           # POST /handle (task = assess | escalate)
│       ├── sentiment.py      # VADER + LLM for borderline
│       ├── summarizer.py     # conversation → structured ticket
│       └── tickets.py        # T-1001, T-1002 ... in tickets.db
│
├── data/
│   ├── corpus/raw/           # the documents we've gathered
│   ├── corpus/processed/     # cleaned markdown, one file per document
│   ├── corpus/manifest.csv   # one row per document (see section 12)
│   ├── db/schema.sql
│   ├── db/seed.py            # 40 synthetic subscribers via Faker
│   └── (generated, gitignored) chroma/, bm25.pkl, telecare.db, auth.db, tickets.db, audit.db
│
├── eval/
│   ├── ir_testset.jsonl      # ~25 questions + the doc that answers each
│   ├── run_ir_eval.py        # P@3, Recall@5, MRR for bm25 / dense / hybrid
│   ├── intent_testset.jsonl  # ~50 labelled messages
│   ├── run_intent_eval.py
│   └── results/              # CSVs + charts that go into the report
│
├── tests/
│   ├── test_envelope.py
│   ├── test_security.py      # SQL injection, prompt injection, no token, other user's data
│   ├── test_bill_diff.py
│   ├── test_routing.py
│   └── test_demo_story.py    # the full conversation, LLM in mock mode
│
├── ui/
│   ├── app.py                # Streamlit chat + login sidebar + agent-trace panel
│   └── pages/console.py      # (Should) human agent ticket console
│
└── docs/
    ├── BUILD_PLAN.md         # this file
    ├── architecture.png
    ├── message_protocol.md
    ├── responsible_ai.md
    └── security_test_log.md
```

Three stores are kept apart on purpose: **telecare.db** (subscriber data, read-only), **auth.db** (OTP codes, writable), and **tickets.db** (supervisor's). This mirrors the trust boundaries we described at mid-eval.

## 4. Shared contracts (merge these first)

The envelope, the intent list and the endpoint shapes are the glue. They go into `shared/` in the first two days; after that, nobody changes them without telling the group.

### The message envelope

```python
# shared/envelope.py
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4
from pydantic import BaseModel, Field
from shared.intents import Intent

Agent = Literal["orchestrator", "knowledge_agent", "account_agent", "supervisor_agent"]

class Envelope(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    sender_agent: Agent
    receiver_agent: Agent
    intent: Intent
    payload: dict
    auth_token: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

def make_reply(req: Envelope, status: str, result: dict) -> Envelope:
    return Envelope(conversation_id=req.conversation_id,
                    sender_agent=req.receiver_agent, receiver_agent=req.sender_agent,
                    intent=req.intent, payload={"status": status, **result})
```

Reply `status` values: `ok`, `needs_auth`, `not_found` (nothing reliable retrieved), `escalate`, `error`.

### Intents and who owns them

| Intent | Owner agent | Login needed |
| --- | --- | --- |
| package_info, tariff_query, roaming_advice, coverage_or_outage_info, troubleshooting, plan_advice | Knowledge Agent | No |
| bill_enquiry, quota_check | Account Agent | Yes |
| complaint | Supervisor Agent | No |
| out_of_scope | Orchestrator answers itself (polite refusal) | No |

### Endpoints

| Service | Endpoint | Called by |
| --- | --- | --- |
| Orchestrator :8000 | `POST /chat` {conversation_id, message} | UI |
| Orchestrator :8000 | `POST /auth/login`, `POST /auth/verify-otp` | UI (proxied to Account Agent) |
| Knowledge :8001 | `POST /handle` (Envelope → Envelope) | Orchestrator |
| Account :8002 | `POST /handle`, `POST /auth/login`, `POST /auth/verify-otp` | Orchestrator |
| Supervisor :8003 | `POST /handle` with payload.task = `assess` or `escalate` | Orchestrator |
| All | `GET /health` | `run_all.py`, UI status dot |

Every specialist call carries an `X-Internal-Key` header from `.env`; a call without it gets 401. `shared/http.py` adds it, plus a 20-second timeout and one retry.

### Audit log

Every decision is one row in `audit.db`: time, conversation_id, agent, decision (e.g. `route→account_agent`, `auth_required`, `retrieval_insufficient`, `escalate`), and the reason. This is our accountability evidence and feeds the UI's agent-trace panel. It never stores raw message text, only the decision.

## 5. Agent 1 — Care Orchestrator

The orchestrator runs the same decision loop on every message. Each step can end the turn early, which is what makes it an agent rather than a pipe.

### The per-message decision loop (`router.py`)

1. **Rate limit** — slowapi, 20 requests/minute per conversation. Over the limit → polite "please slow down".
2. **Sanitize** — strip HTML/control characters, cap length at 1,000 characters (`shared/security.sanitize`).
3. **Injection check** — pattern list ("ignore previous instructions", "system prompt", "reveal all", "act as" …) plus a heuristic score. Blocked → refuse, log `injection_blocked`, stop.
4. **NLU** — one LLM call returns intent + entities as JSON (below). Regex/spaCy fill in what they can first.
5. **Assess** — call Supervisor with `task=assess`. If it says escalate (frustration, "talk to a human", complaint, or two failed answers in a row) → call Supervisor `task=escalate`, return the ticket message, stop.
6. **Auth gate** — intent needs login and the conversation has no valid token → reply `needs_auth` (UI shows the login form), stop.
7. **Route** — send the envelope to the owning agent (intent table above).
8. **Handle the result** — `ok` → compose; `not_found` → say so honestly and offer a human; `error` → apologise and offer a human.
9. **Compose** — add sources, add the AI disclosure on the first turn, write the audit row, return.

### NLU: intent + entities in one call (`nlu.py`)

| Entity | Method | Example |
| --- | --- | --- |
| Phone number | Regex `(?:\+94\|0)7\d{8}` | 0712345678 |
| Amount | Regex `Rs\.?\s?[\d,]+` | Rs. 1,000 |
| Date | spaCy `DATE` | "on the 5th" |
| Country (roaming) | spaCy `GPE` | India |
| Package name, data size | LLM, from the JSON below | "Anytime 5GB" |

The LLM is asked for strict JSON, validated with Pydantic; invalid JSON is retried once, then falls back to a keyword classifier so the system never crashes on a bad reply.

```json
{"intent": "bill_enquiry", "confidence": 0.91,
 "entities": {"package_name": null, "country": null, "data_amount": null},
 "needs_clarification": false}
```

If `confidence` is below 0.5 or `needs_clarification` is true, the orchestrator asks one clarifying question instead of guessing.

### Conversation state (`session.py`)

An in-memory dict keyed by `conversation_id`: last 10 turns, current token, failed-answer counter, whether the AI disclosure was shown. In-memory is fine for a demo; say in the report that production would use Redis.

## 6. Agent 2 — Telecom Knowledge Agent (the IR module)

This agent carries the most marks and is built first. It has two halves: an offline ingest script that builds the indexes once, and an online `/handle` that retrieves, judges and answers.

### Offline: ingesting our documents (`ingest.py`)

Run with `python -m agents.knowledge_agent.ingest`, and again whenever the corpus changes.

1. **Load** each file listed in `manifest.csv` — PDF via pypdf, DOCX via python-docx, HTML via BeautifulSoup, MD/TXT as is.
2. **Clean** — remove headers, footers, cookie banners, repeated navigation; normalise whitespace; save to `corpus/processed/<doc_id>.md` so a human can check it.
3. **Chunk** — split on headings and paragraphs first, then pack to about 400 tokens with ~60 tokens of overlap. **Tariff tables are special:** each package row becomes its own chunk, prefixed with the package name and the table's column names, so "Anytime 5GB costs Rs. 999" is one retrievable unit.
4. **Attach metadata** to every chunk: `doc_id`, `title`, `category`, `operator`, `source_url`, `chunk_id`.
5. **Embed** with `all-MiniLM-L6-v2` (384-dim, normalised, runs on CPU) and store in a ChromaDB persistent collection with cosine distance.
6. **Build BM25** with rank_bm25 over the same chunks (lowercase tokens, keep numbers like `1000` and `5gb`), saved to `bm25.pkl`.

### Online: answering (`retriever.py`, `generator.py`)

1. **Filter by category** when the intent implies one (roaming_advice → `roaming`, plan_advice → `package`).
2. **Retrieve** top-10 by embeddings and top-10 by BM25.
3. **Fuse** with Reciprocal Rank Fusion: score = Σ 1 / (60 + rank). Keep the top 4. RRF needs no score tuning.
4. **Judge sufficiency** — the agentic decision. If the best cosine similarity is under the threshold (start at 0.35, tune on the test set) the evidence is weak.
5. **Retry once** (Should tier) — ask the LLM to rewrite the query in telecom terms, retrieve again. Still weak → return `not_found`. Never answer from memory.
6. **Generate** — prompt with the 4 numbered chunks; rules: answer only from them, cite as [1], [2], say "I don't have that information" if they don't cover it. Return the answer plus a `sources` list (title, URL, chunk id).

### Plan-fit advice

Same pipeline with the `package` filter and a different prompt: recommend the best-fit package from the retrieved ones, give two reasons tied to what the user said, and end with "This is a suggestion; check the details before switching." It does not calculate costs against real usage — we say so at the viva.

### What a good corpus looks like

Aim for 20–40 documents across all categories: 8+ package/tariff pages, 4+ roaming, 3+ coverage/outage notices, 6+ troubleshooting guides, 3+ FAQs, 2+ policies (fair usage, billing). Thin categories show up immediately as low IR scores.

## 7. Agent 3 — Subscriber-Account Agent (the security showcase)

This agent answers bill and quota questions for exactly one logged-in subscriber. **The subscriber ID always comes from the verified token, never from the message text** — so typing someone else's number does nothing.

### Database (`schema.sql`, `seed.py`)

| Table | Key columns | Notes |
| --- | --- | --- |
| subscribers | subscriber_id, msisdn, full_name_enc, email_enc, nic_enc, password_hash, plan_id | Name/email/NIC Fernet-encrypted; msisdn plain (login ID) |
| plans | plan_id, name, monthly_fee, data_gb, voice_min | Names match packages in the corpus |
| bills | bill_id, subscriber_id, period (YYYY-MM), base_fee, addons, roaming, overage, tax, total | Two periods per subscriber |
| bill_items | bill_id, item_date, type, description, amount | Lets us say "add-on on the 12th" |
| usage | subscriber_id, period, data_used_gb, voice_used_min | For quota_check |
| payments | subscriber_id, paid_on, amount, method | "Did my payment go through?" |

`seed.py` uses Faker to create 40 subscribers with two months of bills. About a third get a deliberate change between months (a data add-on, a roaming charge, an overage). One fixed demo subscriber always has the exact numbers from our demo story (Rs. 1,200 add-on on the 12th) and a known password, documented in the README.

The agent opens `telecare.db` with `sqlite3.connect("file:data/db/telecare.db?mode=ro", uri=True)`. Any write attempt raises an error — our read-only proof.

### Login flow (`auth.py`)

1. `POST /auth/login` {msisdn, password} → `bcrypt.checkpw`. Same error message for "wrong number" and "wrong password". Rate-limited to 5/minute.
2. On success, generate a 6-digit OTP with `secrets`, store its hash in `auth.db` with a 5-minute expiry and 3 attempts. Show it in a clearly labelled *simulated SMS* box in the UI.
3. `POST /auth/verify-otp` → check hash, expiry, attempts → issue a JWT (HS256, `sub` = subscriber_id, 15-minute expiry).
4. Every `/handle` call verifies the JWT signature and expiry first. Invalid or missing → `needs_auth`.

### Answering (`repository.py`, `bill_diff.py`)

- Every query is parameterised and filtered by the token's subscriber_id: `SELECT ... FROM bills WHERE subscriber_id = ? AND period IN (?, ?)`.
- `bill_diff.py` is pure Python: compare the two bills, list new bill_items, return a structured diff: `{"change": 1200, "drivers": [{"item": "Data add-on 10GB", "date": "2026-10-12", "amount": 1200}], "base_plan_changed": false}`.
- The LLM only turns that diff into a friendly sentence. It receives amounts and item descriptions — never the name, number or NIC.
- quota_check is a direct lookup (plan allowance − usage).

## 8. Agent 4 — Care Supervisor Agent (human-in-the-loop)

### `task = assess` (every turn, must be fast)

| Signal | How it's detected | Result |
| --- | --- | --- |
| Strong negative sentiment | VADER compound ≤ −0.5 | escalate, priority high |
| Borderline sentiment | VADER between −0.5 and −0.2 → one LLM call to confirm | escalate only if LLM says frustrated |
| Asks for a person | Keywords: "human", "agent", "manager", "call me" | escalate, priority normal |
| Intent is complaint | From the orchestrator's NLU | escalate |
| System keeps failing | 2 `not_found` or `error` replies in a row | escalate, priority normal |

Returns `{sentiment, score, escalate, reason, priority}`. The reason goes to the audit log.

### `task = escalate`

1. Mask PII in the conversation history.
2. One LLM call summarises it into strict JSON: `{issue, key_entities, what_was_tried, customer_mood, priority}`.
3. Store as a ticket in `tickets.db` with the next sequential ID (T-1001, T-1002 …), status `open`.
4. Return: apology, ticket number, "a human agent will contact you within 24 hours" (our pilot SLA assumption).

The optional console page (`ui/pages/console.py`) lists open tickets with their summaries.

## 9. Shared LLM layer and security checklist

### `shared/llm.py`

- `generate(system, prompt, json_schema=None, temperature=0.2)` → text or validated JSON.
- Provider order from `.env`: Gemini (free tier) → Groq/Llama on error or rate limit → `mock` for tests.
- **PII masking is applied inside the client to every outgoing prompt** — phone numbers, NIC numbers, emails and known names become `[PHONE]`, `[NIC]`, `[EMAIL]`, `[NAME]`.
- 30-second timeout, 2 retries with backoff, JSON repair-then-retry once.
- Logs provider, latency and token counts (no prompt text).
- Model names live in `.env`. Pick whichever Flash-tier Gemini and Llama models the free tiers currently offer, and check their rate limits before the demo.

### Security controls mapped to code and tests

| Control | Where | Library | Proven by |
| --- | --- | --- | --- |
| Input sanitization + length cap | Orchestrator step 2 | stdlib `re`, `html` | HTML/script input is stripped |
| Prompt-injection filter | Orchestrator step 3 | pattern list | 10 known injection strings blocked |
| Rate limiting | Orchestrator `/chat`, Account `/auth/*` | slowapi | 21st request in a minute gets 429 |
| Password hashing | Account `auth.py` | `bcrypt` | Seed stores hashes only |
| OTP (hashed, expiring, 3 tries) | Account `auth.py` | `secrets`, `hashlib` | Expired / 4th attempt rejected |
| JWT sessions | Account issues + verifies | PyJWT | Tampered or expired token → `needs_auth` |
| Scoped, parameterised SQL | `repository.py` | sqlite3 `?` params | `' OR 1=1 --` returns nothing extra |
| Read-only data access | Account DB connection | SQLite `mode=ro` | Write attempt raises |
| Field encryption at rest | subscribers table | `cryptography` Fernet | DB shows ciphertext for names |
| PII masking before LLM | `shared/llm.py` + agents | regex | Mock LLM captures prompt; no phone/name in it |
| Service-to-service auth | All specialists | `X-Internal-Key` header | Direct call without key → 401 |
| Secrets management | `.env` + `.gitignore` | python-dotenv | No key in Git history |

Use the `bcrypt` package directly rather than passlib, and PyJWT rather than python-jose (both older choices are poorly maintained). They explain identically at the viva.

## 10. Responsible AI, UI and evaluation

| Principle | Mechanism in code | Evidence for report / viva |
| --- | --- | --- |
| Transparency | First reply says "I'm TeleCare's AI assistant"; UI banner | Screenshot |
| Explainability | Knowledge answers list sources; agent-trace panel shows intent → route → decision | Screenshot of trace |
| Fairness | Same quality across packages and question styles; English-only limit stated in UI | Accuracy broken down by category |
| Privacy | Synthetic data; PII masking; encryption; login first; audit log stores decisions only | Masked-prompt test, ciphertext screenshot |
| Security / misuse | Injection filter, telecom-only scope, rate limits | Security test log |
| Domain risk | Plan advice labelled "suggestion"; Account Agent read-only; human owns any change | `mode=ro` test, sample reply |
| Hallucination | Answer only from retrieved chunks; `not_found` instead of guessing | Groundedness check |

### UI (`ui/app.py`, Streamlit)

- **Chat pane** — messages, each answer's sources in an expandable box.
- **Sidebar** — login form (number + password), then the *simulated SMS* OTP box; logout.
- **Agent-trace panel** (toggle) — per turn: intent + confidence, entities, sentiment score, handling agent, decision and why, latency. The best answer to "where is the agentic behaviour?"
- **Status dots** — green/red per agent from `/health`.
- Footer: "AI assistant · English only · answers from published operator documents".

### Evaluation

| What | How | Size | Metric |
| --- | --- | --- | --- |
| Retrieval | `run_ir_eval.py`: each question has the doc_id that answers it; BM25-only, dense-only, hybrid | 25–30 questions | Precision@3, Recall@5, MRR |
| Intent classification | `run_intent_eval.py`, incl. Sri Lankan English phrasing | ~50 messages | Accuracy, confusion matrix |
| Answer groundedness | Two members independently mark 20 answers | 20 answers | % grounded, % correct |
| End-to-end | 10 scripted conversations incl. the demo story | 10 | Task success %, avg latency |
| Security | Each attack in the checklist, run and recorded | ~15 attacks | Blocked / not blocked |

Write the IR test questions **from the documents, before tuning anything**, and don't change them afterwards.

## 11. Week-by-week build plan

```
 Week 7                 Week 8                Week 9 (FREEZE)        Week 10
 Foundations +          Account Agent +       Supervisor +           Deliverables
 Knowledge Agent        security              integration + eval     and submission
 ─────────────────  →   ─────────────────  →  ─────────────────  →   ─────────────────
 GATE: package Q        GATE: bill answered   GATE: demo story       GATE: video, report
 answered with source   after OTP; others'    end-to-end; numbers    and repo submitted
 in the UI              data unreachable      ready for report
```

Week 11 is the viva. If a gate isn't met, the next week starts by finishing it — and the cut list kicks in.

### Week 7

- [ ] Create repo, folder structure, `.env.example`, `.gitignore`, README stub (M1)
- [ ] Merge `shared/envelope.py`, `shared/intents.py`, `shared/http.py` by day 2 (M1)
- [ ] `shared/llm.py` with Gemini, Groq and mock providers (M4)
- [ ] Clean the corpus, fill `manifest.csv`, write `ingest.py`, build Chroma + BM25 (M2)
- [ ] Write the IR test questions before tuning anything (M2)
- [ ] Knowledge `/handle` with hybrid retrieval and cited answers (M2)
- [ ] Orchestrator `/chat` with NLU, routing knowledge intents only (M1)
- [ ] Streamlit chat showing answers and sources (M1)
- [ ] Everyone runs the full setup on their own laptop (all)

### Week 8

- [ ] `schema.sql` + `seed.py` with the fixed demo subscriber (M3)
- [ ] Login → OTP → JWT, rate-limited (M3)
- [ ] `bill_diff.py` + quota lookup with tests (M3)
- [ ] `shared/security.py`: sanitize, injection filter, PII mask, Fernet (M3)
- [ ] Orchestrator auth gate + UI login sidebar with simulated SMS box (M1)
- [ ] Supervisor `assess` with VADER + rules (M4)
- [ ] Audit log + agent-trace panel (M4 + M1)

### Week 9

- [ ] Supervisor `escalate`: summary → ticket T-1001… (M4)
- [ ] Full demo story passes `test_demo_story.py` in mock mode and live (M1)
- [ ] Run IR eval for 3 configs; export tables and a chart (M2)
- [ ] Intent eval on ~50 messages (M4)
- [ ] Run every attack; fill `security_test_log.md` (M3)
- [ ] Groundedness check on 20 answers (two members)
- [ ] Feature freeze at end of week; tag `v0.9`

### Week 10

- [ ] Report in the lecturer's template, each member writing their own part (all)
- [ ] Record screen demos early, then build the Gen-AI video (M4 leads)
- [ ] README: setup, usage, screenshots, contributors table (M1)
- [ ] Bug fixes only; tag `v1.0`; submit
- [ ] Mock viva: each member explains their agent, the protocol and the full flow

## 12. Team, setup, risks and the corpus

### Who builds what

| Member | Owns (builds + explains at viva) | Also responsible for |
| --- | --- | --- |
| M1 | Orchestrator, `shared/envelope.py`, `shared/http.py`, Streamlit UI, `run_all.py` | Integration, demo story test |
| M2 | Knowledge Agent, ingest, corpus cleaning | IR test set + IR evaluation |
| M3 | Account Agent, schema + seed, auth, `shared/security.py` | Security tests + security test log |
| M4 | Supervisor Agent, `shared/llm.py`, audit log | Intent eval, Responsible AI doc, video |

Everyone reviews at least one other member's pull request each week.

### Git workflow

- `main` is protected; work on `feat/<agent>-<thing>` branches; merge by pull request with one review.
- Small commits with clear messages — the viva checks individual contribution.
- Each agent must pass its own tests with `LLM_PROVIDER=mock` before merging.

### Setup

Python 3.11, one virtual environment. Free API keys from Google AI Studio (Gemini) and the Groq console.

```
# requirements.txt
fastapi
uvicorn[standard]
pydantic
pydantic-settings
httpx
python-dotenv
google-genai
groq
sentence-transformers
chromadb
rank-bm25
spacy            # then: python -m spacy download en_core_web_sm
vaderSentiment
pypdf
python-docx
beautifulsoup4
bcrypt
PyJWT
cryptography
slowapi
streamlit
faker
pytest
```

Pin exact versions once everything installs on all four laptops (`pip freeze > requirements.txt`). On Windows, install the CPU-only PyTorch build first if sentence-transformers is slow to install.

```
# .env.example
LLM_PROVIDER=gemini            # gemini | groq | mock
GEMINI_API_KEY=
GEMINI_MODEL=
GROQ_API_KEY=
GROQ_MODEL=
JWT_SECRET=                    # long random string
FERNET_KEY=                    # Fernet.generate_key()
INTERNAL_API_KEY=              # long random string
RETRIEVAL_MIN_SIMILARITY=0.35
ORCHESTRATOR_PORT=8000
KNOWLEDGE_PORT=8001
ACCOUNT_PORT=8002
SUPERVISOR_PORT=8003
```

### Risks and cut lines

| Risk | Mitigation | If we run out of time |
| --- | --- | --- |
| Free-tier rate limits during demo or video | Groq fallback; mock mode; record the video early | Demo from a recorded run |
| Messy documents (scanned PDFs, tables) | Clean tariff tables by hand into markdown | Drop unreadable documents |
| Integration breaks late | Contracts on day 1–2; mock LLM; `/health` checks; integrate weekly | — |
| Heavy installs on some laptops | Verify setup on all four machines in Week 7 | Run everything on one laptop for the demo |
| A member falls behind | Weekly check against the gates | Merge Supervisor into Orchestrator (3 agents still passes) |

Cut in this order if needed: docker-compose → console page → query-rewrite retry → LLM confirmation of borderline sentiment. **Never cut:** RAG with citations, login/OTP/JWT, escalation, the evaluation numbers.

### Corpus manifest

Put the documents in `data/corpus/raw/` and list each in `data/corpus/manifest.csv`:

```csv
doc_id,file,title,category,operator,source_url,retrieved_on
D001,dialog_anytime_packages.pdf,Anytime Data Packages,package,Dialog,https://...,2026-09-20
D002,roaming_india.html,Roaming Rates — India,roaming,SLT-Mobitel,https://...,2026-09-21
```

- **category** is one of: `package`, `tariff`, `roaming`, `coverage`, `troubleshooting`, `faq`, `policy`.
- Keep the **source_url** for every document — it becomes the citation the user sees.
- Only public operator material; no real customer data anywhere in the corpus.
