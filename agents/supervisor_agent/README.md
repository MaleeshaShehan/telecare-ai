# Supervisor Agent — builder guide

Port **8003** · Endpoints **POST /handle** (`task` = assess | escalate), **GET /tickets** · Owner: you, end to end.

You are building the human-in-the-loop part of the system: the Responsible AI
story the examiners will ask about. You do not need to touch the Orchestrator,
the UI, or anything in `shared/`. The Orchestrator already calls you on every
turn and hands over the conversation when you say so.

---

## 1. What this agent is

The **floor manager**. It watches every customer message for frustration,
decides whether a human should take over, and when the answer is yes it
summarises the whole conversation into a ticket with a reference number so the
customer never has to repeat themselves.

Decisions this agent makes on its own: does this situation need a human, and at
what priority. That is a judgement call, which is what makes it an agent.

---

## 2. The contract

The Orchestrator sends one `Envelope` per call and reads `payload.task`.

### 2a. `task = "assess"` — called on **every** customer turn, before routing

Must be fast (tens of milliseconds). Use VADER locally; call the LLM only for
borderline cases.

Request payload:

```json
{"task": "assess", "message": "This is ridiculous, I've had billing problems for weeks!",
 "intent": "complaint", "failed_count": 0}
```

`failed_count` is how many consecutive `not_found`/`error` replies this
conversation has had. `intent` is the Orchestrator's classification.

Reply — `make_reply(env, "ok", {...})`:

```json
{"status": "ok", "sentiment": "negative", "score": -0.72, "escalate": true,
 "reason": "vader<=-0.5", "priority": "high"}
```

| key | values |
| --- | --- |
| sentiment | `positive` · `neutral` · `negative` |
| score | VADER compound, −1.0 to 1.0 |
| escalate | `true` / `false` |
| reason | short machine-readable string, goes to the audit log, e.g. `vader<=-0.5`, `asked_for_human`, `repeated_failures`, `llm_confirmed_frustrated`, `none` |
| priority | `high` · `normal` · `low` |

**Escalation rules you implement:**

| Signal | Detection | Result |
| --- | --- | --- |
| Strong negative sentiment | VADER compound ≤ −0.5 | escalate, `high` |
| Borderline sentiment | −0.5 < compound ≤ −0.2 → one `shared.llm.generate` call asking "is this customer frustrated? yes/no" | escalate only if yes, `normal` |
| Asks for a person | keywords: human, agent, manager, call me, speak to someone | escalate, `normal` |
| System keeps failing | `failed_count >= 2` | escalate, `normal` |
| Intent is complaint | the Orchestrator escalates this itself; you may also flag it | escalate |

If your agent is down or returns anything but `ok`, the Orchestrator logs
`assess_unavailable` and continues without escalation. Your outage never
breaks a turn, but it does remove the safety net, so keep assess simple and
reliable.

### 2b. `task = "escalate"` — called when assess said yes, or intent is complaint

Request payload:

```json
{"task": "escalate",
 "history": [{"role": "user", "text": "Why is my bill higher this month?"},
             {"role": "assistant", "text": "Your bill went up Rs. 1,200 …"},
             {"role": "user", "text": "This is ridiculous, I've had billing problems for weeks!"}],
 "reason": "vader<=-0.5", "priority": "high"}
```

`history` is the last 10 turns, raw. **You mask PII before anything leaves
this process** (`shared.security.mask_pii` on every text; `shared.llm.generate`
masks again as a safety net).

Reply — `make_reply(env, "escalate", {...})`:

```json
{"status": "escalate", "ticket_id": "T-1042", "priority": "high",
 "answer": "I'm sorry about the trouble. I've created ticket T-1042 with your full case details; a human agent will contact you within 24 hours."}
```

`ticket_id` format: `T-` + 4 digits, sequential, starting at `T-1001`.

### 2c. `GET /tickets` — for the human agent console

Requires `X-Internal-Key` (the Orchestrator proxies it to the browser). Return
a JSON list, newest first:

```json
[{"ticket_id": "T-1042", "created_at": "2026-10-08T10:17:03Z", "priority": "high",
  "status": "open", "issue": "Disputes Rs. 1,200 add-on charge; unresolved for weeks",
  "customer_mood": "frustrated", "conversation_id": "…"}]
```

---

## 3. What the UI does with your reply

- `answer` is shown in the bubble with an amber left border.
- `ticket_id` and `priority` render an amber ticket card with a copy button and the 24-hour promise.
- `console.html` lists `GET /tickets` as a table: ticket, opened, priority pill (high red, normal amber, low green), issue, mood, status. Refreshes every 10 s.

---

## 4. Files and what goes where

```
agents/supervisor_agent/
├── README.md        this guide
├── __main__.py      python -m agents.supervisor_agent
├── main.py          FastAPI app: /health, /handle, /tickets. Replace the stub bodies.
├── sentiment.py     assess(message, intent, failed_count) → dict   (VADER + rules + borderline LLM)
├── summarizer.py    summarize(history) → {issue, key_entities, what_was_tried, customer_mood, priority}
├── tickets.py       create_ticket(conversation_id, summary, priority) → "T-1001"; list_open_tickets()
└── examples/        sample envelopes for scripts/ping_agent.py

data/db/tickets.db   generated (gitignored) if you use SQLite
ui/web/console.html  already built; reads /tickets through the Orchestrator
docs/responsible_ai.md  you write this (section 9 of docs/BUILD_PLAN.md expanded)
```

---

## 5. Shared helpers you use, files you must not edit

Use:

- `shared.envelope.Envelope`, `make_reply`
- `shared.llm.generate(system, prompt, json_schema=…)` — for the borderline check and the ticket summary. Pass a `json_schema` with `required` keys and you get a dict back. In mock mode you get a dict with those keys set to `None`; your code must handle that and still create a ticket (use fallback text).
- `shared.security.mask_pii`
- `shared.audit.log_decision(conversation_id, "supervisor_agent", decision, reason)` — log `assess`, `escalate`, `ticket_created`. Never log message text.
- `shared.http.require_internal_key`

Do **not** edit: `shared/`, `agents/orchestrator/`, the other agents, `ui/`, `tests/contract/`.

---

## 6. Ticket store: your choice

**SQLite (default):** `data/db/tickets.db`, one table, sequential IDs from
`MAX(id)+1`. Parameterised SQL.

**Supabase:** a `tickets` table; the console then shows live tickets from any
machine. Keys in `.env` (`SUPABASE_URL`, `SUPABASE_KEY`, already in
`shared.config.settings`). Tests must still pass offline, so keep a SQLite or
in-memory path for `pytest`.

---

## 7. Run alone, test alone

```bash
pip install vaderSentiment
python -m agents.supervisor_agent

# from another terminal
python scripts/ping_agent.py supervisor_agent --task assess --message "This is ridiculous, I've had problems for weeks!"
python scripts/ping_agent.py supervisor_agent --task assess --message "Thanks, that helps"
python scripts/ping_agent.py supervisor_agent --file agents/supervisor_agent/examples/escalate.json
python scripts/ping_agent.py supervisor_agent --tickets

LLM_PROVIDER=mock pytest tests/contract/test_contract_supervisor.py -q
python run_all.py          # full system: type the complaint in the UI, then open the console page
```

---

## 8. Build order (each step has a proof)

1. **sentiment.py with VADER only.** Compound score → sentiment label; rules for ≤ −0.5, keywords, `failed_count`.
   *Proof:* the two ping commands above return `escalate: true` and `false` respectively.
2. **Wire assess in main.py.**
   *Proof:* `pytest tests/contract/test_contract_supervisor.py -k assess` green.
3. **tickets.py.** Create table on first use; `create_ticket` returns the next `T-xxxx`; `list_open_tickets`.
   *Proof:* two calls give T-1001 then T-1002.
4. **Wire escalate with a fixed summary.** Mask history, create ticket, return the apology with the real ticket id.
   *Proof:* contract test green; ticket card in the UI; `console.html` shows the row.
5. **summarizer.py.** One `generate` call with a JSON schema; fallback text when mock or when the LLM fails.
   *Proof:* with a real key, the console shows a sensible `issue`; in mock mode the ticket still exists.
6. **Borderline LLM confirmation** for −0.5 < compound ≤ −0.2.
   *Proof:* "hmm, this is a bit annoying" escalates only if the LLM says frustrated.
7. **`GET /tickets`** wired to `list_open_tickets`.
8. **docs/responsible_ai.md** and the commercialisation section for the report.
9. **Video script** (3–5 min: problem 30 s → four agents + demo story 2 min → Responsible AI 45 s → commercialisation 45 s).

---

## 9. Rules that apply to you (Responsible AI)

- A human is always reachable: every escalation ends in a ticket number and a promise.
- Mask PII before summarising. The ticket must not contain a phone number, NIC or email.
- The reason for every escalation goes to the audit log so the decision is explainable afterwards.
- Priority is a judgement, not a script. Be able to explain the thresholds at the viva.

## 10. Definition of done

- [ ] `pytest tests/contract/test_contract_supervisor.py` passes offline in mock mode.
- [ ] "This is ridiculous…" in the UI produces a ticket card with a real sequential id; "Thanks, that helps" does not escalate.
- [ ] The ticket appears in `console.html` with a PII-free summary.
- [ ] `docs/responsible_ai.md` written.
- [ ] You can explain every line in this folder at the viva.
