# TeleCare AI — Agent Message Protocol

Agents communicate over HTTP (REST) with one fixed JSON envelope. This is our
defined agent communication protocol (API-based, A2A-style). The model lives in
`shared/envelope.py`; this page is the human-readable spec to open at the viva.

## Topology

- The UI calls only the Orchestrator (`POST /chat`).
- The Orchestrator calls specialists at `POST /handle`, one per turn.
- Specialists never call each other.
- Every specialist call carries `X-Internal-Key`. Without it: HTTP 401.

## The envelope (8 fields)

| Field | Type | Notes |
| --- | --- | --- |
| message_id | string (UUID) | Generated per message |
| conversation_id | string | Same for the whole chat |
| sender_agent | orchestrator \| knowledge_agent \| account_agent \| supervisor_agent | |
| receiver_agent | same set | |
| intent | one of the 10 intents in `shared/intents.py` | |
| payload | object | Request: query, entities, task. Reply: status + result |
| auth_token | string or null | JWT; present only on requests to the Account Agent |
| timestamp | ISO 8601 UTC | |

## Reply status values

| status | Meaning | Orchestrator reaction |
| --- | --- | --- |
| ok | Answer in payload | Compose and return |
| needs_auth | Login required | UI shows login form |
| not_found | No reliable evidence | Say so honestly, offer a human |
| escalate | Ticket created | Return ticket message |
| error | Specialist failed | Apologise, offer a human |

## Example: request to the Knowledge Agent

```json
{
  "message_id": "6f1c…",
  "conversation_id": "a3b2…",
  "sender_agent": "orchestrator",
  "receiver_agent": "knowledge_agent",
  "intent": "plan_advice",
  "payload": {"query": "heavy home video streaming, evenings", "entities": {}},
  "auth_token": null,
  "timestamp": "2026-10-08T10:15:00Z"
}
```

## Example: reply

```json
{
  "message_id": "9d0e…",
  "conversation_id": "a3b2…",
  "sender_agent": "knowledge_agent",
  "receiver_agent": "orchestrator",
  "intent": "plan_advice",
  "payload": {
    "status": "ok",
    "answer": "Home Fibre 100GB suits evening streaming [1] …",
    "sources": [{"id": 1, "title": "Home Packages", "url": "https://…", "chunk_id": "D004-3"}]
  },
  "auth_token": null,
  "timestamp": "2026-10-08T10:15:01Z"
}
```

## Supervisor tasks

The Supervisor reads `payload.task`. The Orchestrator calls `assess` on every
turn before routing, and `escalate` when assess says so or the intent is
`complaint`.

| task | Request payload | Reply payload |
| --- | --- | --- |
| assess | `{task: "assess", message, intent, failed_count}` | `{status: "ok", sentiment, score, escalate: bool, reason, priority}` |
| escalate | `{task: "escalate", history: [{role, text}], reason, priority}` | `{status: "escalate", ticket_id, answer}` |

If assess returns anything other than `ok`, the Orchestrator logs
`assess_unavailable` and continues the turn without escalation.

## Auth endpoints (Orchestrator → Account Agent, with X-Internal-Key)

| Path | Request | Replies |
| --- | --- | --- |
| POST /auth/login | `{msisdn, password}` | 200 `{otp_sent: true, channel: "simulated", debug_otp: "482913", expires_in: 300}` (UI shows the code) · 200 `{otp_sent: true, channel: "sms", expires_in: 300}` (real SMS, UI says check your phone) · 401 `{detail: "Invalid number or password"}` · 429 |
| POST /auth/verify-otp | `{msisdn, otp}` | 200 `{token, expires_in: 900}` — the Orchestrator stores `token`; the browser only gets `{logged_in: true}` · 401 `{detail: "Code rejected"}` · 429 |

The token is opaque to the Orchestrator and the UI. Only the Account Agent
issues and verifies it (own JWT or a Supabase Auth token).

## Extra payload keys the UI renders as cards

| key | from | shape |
| --- | --- | --- |
| bill_diff | Account | `{change:int, drivers:[{item,date,amount}], base_plan_changed:bool}` |
| quota | Account | `{used_gb:float, allowance_gb:float, period:"YYYY-MM"}` |
| ticket_id, priority | Supervisor | `"T-1042"`, `"high" \| "normal" \| "low"` |

## Per-agent builder guides

`agents/knowledge_agent/README.md` · `agents/account_agent/README.md` ·
`agents/supervisor_agent/README.md` · `agents/orchestrator/README.md`.
Test a running agent in isolation with `python scripts/ping_agent.py <agent> …`;
contract tests live in `tests/contract/`.
