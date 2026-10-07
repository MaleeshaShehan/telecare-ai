# TeleCare AI — Build Plan (ours)

Version 2 · Owner: M1 (team lead) · Supersedes `archive/BUILD_PLAN_v1_7oct.md`

This is the team's working plan. It is written against the actual briefs in
`docs/brief/` and the code that exists today. Update it when a gate is passed
or a decision changes. Every member should be able to open this file at the
viva and point to their part.

---

## 1. What we are building and why

**TeleCare AI** is a tier-1 customer-care system for a Sri Lankan mobile
operator, built as a *digital twin of a real care desk*: a front desk that
understands and routes, a product expert that answers from the operator's own
documents, an accounts clerk with read-only access to one subscriber's data,
and a floor manager who hands hard cases to a human. Each desk is an
autonomous agent. They talk over HTTP with one fixed JSON envelope.

Why telecom: operators receive thousands of repetitive tier-1 contacts a day
(packages, bills, roaming, coverage, "my internet is slow"). The answers already
exist in documents and account systems; they are slow to give out by hand.
Poor service drives churn. Deflecting tier-1 while keeping humans for hard
cases cuts cost and lifts experience.

**The demo story (memorise it):**

1. "Why is my bill higher this month?" → login + OTP → Account Agent: *"Your
   bill rose Rs. 1,200 from a data add-on on the 12th; base plan unchanged."*
2. "I mostly stream video at home in the evenings, what plan suits me?" →
   Knowledge Agent: a cited recommendation from the package documents.
3. "This is ridiculous, I've had problems for weeks!" → Supervisor: ticket
   T-1042, a human will call within 24 hours.

---

## 2. What the assignment asks for, and where we answer it

From `docs/brief/group_assignment_brief.pdf`.

| Requirement | Where it lives | Evidence we will show |
| --- | --- | --- |
| Solve a problem in the selected domain | Telecom tier-1 care overload | Section 1, report intro |
| At least two interacting intelligent agents | Four FastAPI agents; Orchestrator calls three specialists | Trace panel, `docs/message_protocol.md` |
| One or more LLMs | Gemini (primary) → GPT via OpenAI (backup) via `shared/llm.py`; one call site for every agent | Config, provider fallback log |
| NLP techniques | Intent classification + NER (Orchestrator); sentiment + summarisation (Supervisor) | Intent eval accuracy, ticket summaries |
| Information Retrieval module | Hybrid BM25 + dense retrieval with RRF, cited answers (Knowledge Agent) | P@3 / Recall@5 / MRR table, 3 configs |
| Security features | Login + OTP + JWT, bcrypt, parameterised SQL, read-only DB, sanitisation, injection filter, PII masking, Fernet, rate limits, internal key | `security_test_log.md`, tests |
| Defined agent communication protocol | API-based: HTTP + JSON `Envelope` (8 fields, 5 statuses). We do **not** use MCP. | Protocol doc, one real request/reply pair |
| Responsible AI | Grounding + citations, AI disclosure, human-in-the-loop, synthetic data, PII masking, audit log of decisions only, English-only stated | Section 9 table, screenshots |
| Commercialisation with pricing | B2B SaaS to operators; 4 tiers | Report section (from project guide §13) |

**Marks still available** (mid-eval 20 is done):

| Deliverable | Marks | Depends on |
| --- | --- | --- |
| Gen-AI video, 3–5 min | 25 | Demo story running end to end; screen recordings |
| Final report (lecturer's template) | 30 | Eval numbers, security log, screenshots, commercialisation |
| GitHub repository + README | 5 | Clean repo, contributors table, per-member commits |
| Viva | 20 | Each member explains own agent, the protocol, the full flow |

---

## 3. Milestones (in order, no dates)

The project is finished when every milestone below is true. There is no
schedule; each builder works at their own pace on their own agent, and the
lead integrates whenever a piece lands.

| # | Milestone | Proof |
| --- | --- | --- |
| 1 | Knowledge Agent answers a package question with a real citation in the web UI | Source card shows a real document |
| 2 | Account DB seeded; bill question answered after real login + OTP; another subscriber's data unreachable | Bill card in the UI; attack 6 in the security log blocked |
| 3 | Supervisor escalates on sentiment and creates a real sequential ticket | Ticket card; row in the console |
| 4 | The demo story passes live against all real agents | `tests/test_demo_story.py` live variant green |
| 5 | Evidence collected: IR eval table, intent eval, security log, groundedness check | Files in `eval/results/` and `docs/` |
| 6 | Video, report, README complete | Submitted |
| 7 | Every member can explain their agent, the protocol and the full flow | Mock viva done |

---

## 4. Architecture

Unchanged from mid-eval, with one amendment: the UI is a static single-page
app served by the Orchestrator, not Streamlit.

```
            Browser  ──►  http://127.0.0.1:8000/   (ui/web: HTML + CSS + JS, no build step)
                                   │ POST /chat · /auth/* · GET /agents/health · /tickets
        ┌──────────────────────────▼───────────────────────────┐
        │ Care Orchestrator :8000                               │
        │ rate limit → sanitize → injection check → NLU →       │
        │ assess (Supervisor) → clarify? → auth gate →          │
        │ route to ONE specialist → compose + audit             │
        └──────┬──────────────────────┬──────────────────────┬──┘
               │  Envelope over HTTP, X-Internal-Key header   │
   ┌───────────▼─────────┐ ┌──────────▼──────────┐ ┌─────────▼───────────┐
   │ Knowledge :8001     │ │ Account :8002       │ │ Supervisor :8003    │
   │ BM25 + dense (RRF)  │ │ login · OTP · JWT   │ │ assess: VADER+rules │
   │ sufficiency → retry │ │ scoped param. SQL   │ │ escalate → ticket   │
   │ cited answer        │ │ bill diff (Python)  │ │ T-1001, T-1002 …    │
   ├─────────────────────┤ ├─────────────────────┤ ├─────────────────────┤
   │ chroma/ + bm25.pkl  │ │ telecare.db (ro)    │ │ tickets.db          │
   │                     │ │ auth.db (OTP)       │ │                     │
   └─────────────────────┘ └─────────────────────┘ └─────────────────────┘
   shared/: config · envelope · intents · http · llm (PII-masked) · security · audit
```

Rules that do not change: specialists never call each other; every specialist
endpoint needs the internal key; the subscriber ID comes only from the verified
JWT; the browser never receives the JWT; all SQL is parameterised; bill maths
is Python; the Knowledge Agent never answers from model memory.

---

## 5. Status board (update when something lands)

| Component | Owner | State | Tests |
| --- | --- | --- | --- |
| `shared/` contracts: envelope, intents, config, http, audit | M1 | **Done** | 7 |
| `shared/security.py`: sanitize, injection list (11 phrases), PII mask | M1 | **Done** (JWT/Fernet moved into the Account Agent) | 6 |
| `shared/llm.py`: Gemini → GPT fallback (Groq optional), JSON repair, mock | M1 | **Done**, needs one live smoke test with real keys | 11 |
| Builder guides, `scripts/ping_agent.py`, `tests/contract/`, run-alone entry points | M1 | **Done** | 16 |
| Orchestrator: decision loop, NLU, auth proxy, rate limit, sessions | M1 | **Done to contract** (LLM path unverified live) | 29 |
| Web UI (`ui/web`) | M1 | **Done**; cards for bill/quota/ticket wait on real data | manual |
| Knowledge Agent | M2 | **Stub** (canned answer); ingest/retriever/generator are signatures only | 3 (key tests) |
| Account Agent | M3 | **Stub**; schema.sql done; seed, auth, repository, bill_diff empty | 4 (key + needs_auth) |
| Supervisor Agent | M4 | **Stub** (neutral / fixed T-1001); sentiment/summarizer/tickets empty | 3 |
| `run_all.py`, README, protocol doc | M1 | Done | — |
| Eval scripts | M2 / M1 | Signatures only | — |
| Corpus | M2 | **Empty** | — |

Run `LLM_PROVIDER=mock pytest -q` → 53 passed, 1 xfail (bill_diff).

---

## 6. Work packages

**How we work:** one builder per specialist, end to end, so each member learns
the whole stack of their agent and can explain it at the viva. Each agent
folder has a `README.md` builder guide with the contract, worked examples,
files, build order and definition of done. Builders never edit `shared/`,
the Orchestrator, the UI, other agents or `tests/contract/`. They run their
agent alone (`python -m agents.<agent>`), test it alone
(`scripts/ping_agent.py`), and prove the contract (`tests/contract/`).
Data store (SQLite or Supabase) and OTP channel are each builder's choice;
tests must pass offline regardless.

Each package ends with an acceptance test that already exists or is named
here. A member is done when their tests pass and their milestone holds.

### M1 — Orchestrator, UI, integration (lead)

Done: everything in section 5 marked M1. Remaining:

- [ ] Run the NLU LLM path against real Gemini once M4 lands providers; tune `NLU_SYSTEM` until intent eval ≥ 85 %.
- [ ] `eval/run_intent_eval.py` + `eval/intent_testset.jsonl` (~50 messages incl. Sri Lankan English). *Moved from M4: it measures the Orchestrator.*
- [ ] Integration run on one laptop whenever a builder lands a piece; keep `tests/test_demo_story.py` green and add a **live** variant that hits real agents.
- [ ] Review every PR before merge.
- [x] Known-limitations list in README (section 10 of this plan).
- [ ] After the real agents are in: stream trace events to the UI with server-sent events; animated architecture pane; typing effect; demo auto-play for the video.

### M2 — Knowledge Agent (the IR module, most marks)

- [ ] Collect 20–40 public operator documents into `data/corpus/raw/`, one row each in `manifest.csv` (categories: package, tariff, roaming, coverage, troubleshooting, faq, policy). Add a one-line "best for…" to every package page.
- [ ] **Write ~25 IR test questions first** (`eval/ir_testset.jsonl`, question + doc_id). Never change them after tuning starts.
- [ ] `ingest.py`: load (pypdf / python-docx / bs4 / md) → clean → chunk ~400 tokens, 60 overlap; **one chunk per tariff-table row** → metadata → MiniLM embeddings → Chroma; BM25 over the same chunks → `bm25.pkl`.
- [ ] `retriever.py`: `dense_search`, `bm25_search`, `hybrid_search` (RRF, k=60), `is_sufficient` (best cosine ≥ `RETRIEVAL_MIN_SIMILARITY`, start 0.35, tune on the test set early).
- [ ] `generator.py`: grounded answer, [n] citations, "I don't have that information" rule, `sources` list. Plan-advice variant with the suggestion disclaimer.
- [ ] Replace the stub body of `main.py` `handle()`. Return `not_found` on weak evidence. Should-tier: one query rewrite retry.
- [ ] `eval/run_ir_eval.py`: P@3, Recall@5, MRR for bm25 / dense / hybrid → CSV + chart in `eval/results/`.
- Acceptance: "cheapest 5GB anytime package" returns the right document with a citation in the UI; eval table exists.

### M3 — Account Agent + security

- [ ] `data/db/seed.py`: 40 Faker subscribers, two bill periods, ~1/3 with a change; **demo subscriber** with Rs. 1,200 "Data add-on 10GB" on the 12th and a documented password; Fernet-encrypted name/email/NIC; bcrypt hashes. Creates empty `auth.db`, `tickets.db`.
- [ ] `bill_diff.py` until `tests/test_bill_diff.py` passes (remove the xfail).
- [ ] `repository.py`: read-only connection, parameterised queries filtered by subscriber_id.
- [ ] `auth.py` + real `/auth/login` (bcrypt, same error for bad number/password, 5/min) and `/auth/verify-otp` (hashed OTP, 5-min expiry, 3 attempts → JWT). Return `debug_otp` in login response for the simulated-SMS box.
- [ ] `auth.py`: `issue_jwt`, `verify_jwt` (HS256, 15 min) or Supabase Auth token verification; Fernet `encrypt`/`decrypt` for name/email/NIC. (Lives in the Account Agent, not `shared/`.)
- [ ] Choose SQLite or Supabase and the OTP channel (simulated / real SMS with simulated fallback). See `agents/account_agent/README.md` §5–6.
- [ ] `/handle`: verify JWT → subscriber_id → bill_enquiry (diff + LLM phrasing, return `bill_diff` in payload for the UI card) · quota_check (return `quota: {used_gb, allowance_gb}`).
- [ ] `docs/security_test_log.md`: run every attack in section 8, record blocked / not blocked.
- Acceptance: demo subscriber logs in, bill question answered with the card; `' OR 1=1 --` returns nothing extra; write attempt on telecare.db raises; another subscriber's number in the message changes nothing.

### M4 — Supervisor + Responsible AI + video

- [ ] `sentiment.py`: VADER + rules from section 7; LLM confirm for −0.5 < compound ≤ −0.2.
- [ ] `summarizer.py`: PII-mask history → one LLM JSON call → `{issue, key_entities, what_was_tried, customer_mood, priority}`.
- [ ] `tickets.py`: `tickets.db`, sequential T-1001…, `create_ticket`, `list_open_tickets`; wire `GET /tickets`.
- [ ] Replace stub bodies in `main.py` (assess, escalate). Return `ticket_id`, `priority` in the escalate payload.
- [ ] `docs/responsible_ai.md` (section 9 expanded) and the commercialisation section for the report.
- [ ] Video: script, then screen recordings once the demo story runs live, then Gen-AI narration.
- Acceptance: "This is ridiculous…" → ticket with a real summary visible in `console.html`; neutral messages do not escalate.

---

## 7. Contracts (do not change without telling the group)

Full detail with JSON examples: `docs/message_protocol.md`.

- **Envelope**: message_id, conversation_id, sender_agent, receiver_agent, intent, payload, auth_token, timestamp. Replies put `status` in payload: `ok | needs_auth | not_found | escalate | error`.
- **Intents**: package_info, tariff_query, roaming_advice, coverage_or_outage_info, troubleshooting, plan_advice → Knowledge · bill_enquiry, quota_check → Account (login) · complaint → Supervisor · out_of_scope → Orchestrator.
- **Supervisor tasks**: `assess {message, intent, failed_count}` → `{sentiment, score, escalate, reason, priority}` · `escalate {history, reason, priority}` → `{ticket_id, answer}`.
- **Escalation rules**: VADER ≤ −0.5 → high; borderline → LLM confirm; "human/agent/manager/call me" → normal; intent complaint → always; 2 consecutive not_found/error → normal.
- **Auth**: `POST /auth/login {msisdn, password}` → `{otp_sent, debug_otp}` · `POST /auth/verify-otp {msisdn, otp}` → `{token}`. The Orchestrator stores the token; the browser gets `{logged_in: true}` only.
- **UI cards**: any extra payload keys reach the UI as `extra`. Recognised: `bill_diff {change, drivers[{item,date,amount}], base_plan_changed}`, `quota {used_gb, allowance_gb}`, `ticket_id`, `priority`.
- **Audit**: `log_decision(conversation_id, agent, decision, reason)`. Never message text.

---

## 8. Evaluation and evidence (after the real agents are in)

| What | How | Owner | Goes to |
| --- | --- | --- | --- |
| Retrieval quality | 25 questions; P@3, Recall@5, MRR; bm25 vs dense vs hybrid | M2 | Report table + chart |
| Intent accuracy | ~50 labelled messages; accuracy + confusion matrix; LLM path vs keyword fallback | M1 | Report |
| Groundedness | Two members mark 20 answers: grounded? correct? | M2 + M4 | Report |
| End-to-end | 10 scripted conversations incl. demo story; task success %, latency | M1 | Report, video |
| Security | ~15 attacks: SQLi, prompt injection ×10, no token, tampered JWT, expired OTP, 4th OTP attempt, other user's number, direct specialist call without key, 21st request, write to ro DB | M3 | `security_test_log.md` |

---

## 9. Responsible AI (what we do, what we show)

| Principle | Mechanism | Evidence |
| --- | --- | --- |
| Transparency | First reply carries the AI disclosure pill; footer states English-only, document-based | Screenshot |
| Explainability | Citations on every knowledge answer; trace panel shows intent → assess → route → result | Screenshot of trace |
| Fairness | Same pipeline for every package and subscriber; English-only limit stated, Sinhala/Tamil as future work | Accuracy by category |
| Privacy | Synthetic data; login before account data; PII masked before any LLM call; Fernet at rest; audit stores decisions only; JWT never in browser | Masked-prompt test, ciphertext screenshot |
| Safety / misuse | Sanitisation, injection filter, telecom-only scope, rate limits, internal key | Security log |
| Human in the loop | Supervisor escalation with ticket; "Talk to a human" on every failure | Ticket card, console |
| Hallucination | Answer only from chunks; `not_found` instead of guessing; bill maths in Python | Groundedness check |
| Accountability | Every decision logged with reason | `audit.db` |

---

## 10. Assignment 2 readiness (individual red-team audits)

`docs/brief/individual_assignment_brief.pdf` — each member later audits the
finished system from one specialisation and needs ≥ 15 test cases with
evidence. We do **not** build for it now, but the system should produce
evidence and have honest, documented weak spots. Current state:

| Specialisation | Evidence the system produces | Known weak spots (legitimate findings) |
| --- | --- | --- |
| 1 · Prompt injection / jailbreak | `injection_blocked` in trace; masked prompts in mock mode | Filter is a short phrase list, easily paraphrased; NLU system prompt is a plain string (leakage possible); no output-side check on Knowledge answers |
| 2 · Privacy / data leakage | JWT server-side; PII mask test; Fernet fields; audit without text | Session keyed by browser-generated conversation_id (knowing it = using its login); `/auth/status` lets you probe IDs; in-memory sessions; 15-min JWT not refreshed |
| 3 · Responsible AI / bias | Disclosure, citations, `not_found`, escalation | Keyword fallback intents are English-centric; plan advice is retrieval-based not cost-based (we say so); VADER on Sri Lankan English untested |
| 4 · IR and API security | Internal key 401 test; hybrid eval; sufficiency threshold | Threshold tuning on the same test set; corpus poisoning via a bad document; rate limit resets per conversation_id; no TLS between agents (localhost) |

Put the weak spots in the README under *Known limitations*. A documented
limitation is a mature engineering statement, not a lost mark.

---

## 11. Risks and cut lines

| Risk | Mitigation | Fallback |
| --- | --- | --- |
| Free-tier LLM limits during demo/video | GPT fallback; mock mode; record video early | Demo from recording |
| Messy PDFs / tariff tables | Hand-clean tables into markdown | Drop unreadable docs |
| Heavy installs on a laptop | Verify setup on all four machines early; CPU-only torch | Demo from one laptop |
| A builder is blocked | Lead pairs on the blocker | Merge Supervisor into Orchestrator (3 agents still passes) |
| Report/video started too late | Report skeleton from this document; record screens as soon as the demo story runs live | — |

Cut in this order if needed: SSE trace streaming → demo auto-play → docker-compose → query-rewrite retry → LLM confirmation of borderline sentiment → console page.
**Never cut:** cited RAG, login/OTP/JWT, escalation to ticket, the evaluation numbers.

---

## 12. Working agreements

- `main` is protected. Branches `feat/<agent>-<thing>`. One review per PR. Small commits with clear messages — the viva checks individual contribution.
- Every change ships with or updates a pytest. `LLM_PROVIDER=mock pytest -q` must pass before merge.
- Plain Python. No LangChain / CrewAI. If you cannot explain a line, do not ship it.
- `shared/` changes are announced in the group chat before merging.
- No secrets in Git. `.env` only. Synthetic data only.
- Whenever a piece lands: integration run on the lead's laptop, milestone check, update section 5 of this file.
