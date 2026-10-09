# Account Agent — builder guide

Port **8002** · Endpoints **POST /handle**, **POST /auth/login**, **POST /auth/verify-otp** · Owner: you, end to end.

You are building the security showcase. You do not need to touch the
Orchestrator, the UI, or anything in `shared/`. The Orchestrator already
proxies login and OTP to you, stores whatever token you issue, and sends it
back on every account question. The UI already shows a simulated-SMS box or a
"check your phone" hint depending on what your login endpoint returns.

---

## 1. What this agent isx

The **accounts clerk**. After a subscriber proves who they are, it answers
questions about *their* bill and data balance from a database it can only
read. It explains why this month's bill differs from last month's, with the
arithmetic done in Python and the LLM only phrasing the result.

Decisions this agent makes on its own: is this session allowed to see data at
all, and which stored fields answer the question.

**Hard rules (these are graded):**

1. The subscriber ID comes **only** from the verified token, never from message text. If an account request names a different or malformed mobile number, return `forbidden` without reading account data. The verified subscriber may name their own number.
2. The runtime database connection is **read-only** and you can prove it with a failed write.
3. All SQL is parameterised. No string-built SQL anywhere.
4. Bill maths is pure Python in `bill_diff.py`. The LLM receives amounts and item descriptions, never name, number or NIC.
5. Login is passwordless. OTPs are stored as bcrypt hashes with expiry and attempt limits. Name, email and NIC are Fernet-encrypted at rest.
6. All data is synthetic.

---

## 2. The contract

### 2a. `POST /handle` — account questions

**Intents routed to you:** `bill_enquiry`, `quota_check`. The Orchestrator
already refuses to route these without a token, but you must verify the token
yourself too (defence in depth; a direct caller could skip the Orchestrator).

Request you receive:

```json
{
  "message_id": "…", "conversation_id": "…",
  "sender_agent": "orchestrator", "receiver_agent": "account_agent",
  "intent": "bill_enquiry",
  "payload": {"query": "Why is my bill higher this month?", "entities": {"phone": [], "amount": [], "date": [], "country": null, "package_name": null, "data_amount": null}},
  "auth_token": "<the exact string you returned from /auth/verify-otp>",
  "timestamp": "…"
}
```

Reply — `make_reply(env, status, result)`:

| status | When | `result` keys |
| --- | --- | --- |
| `needs_auth` | No token, invalid signature, expired, unknown subscriber | none (optional `reason`) |
| `ok` (bill_enquiry) | Two bills found and compared | `answer: str` · `bill_diff: {change:int, drivers:[{item,date,amount}], base_plan_changed:bool}` |
| `ok` (quota_check) | Usage found | `answer: str` · `quota: {used_gb:float, allowance_gb:float, period:"YYYY-MM"}` |
| `not_found` | No bills / no usage for this subscriber | `reason` |
| `error` | DB or LLM failure | `reason` |

Example `ok` for the demo subscriber:

```json
{
  "status": "ok",
  "answer": "Your bill went up by Rs. 1,200 compared with last month. The difference comes from a Data add-on 10GB activated on the 12th; your base plan is unchanged.",
  "bill_diff": {"change": 1200, "drivers": [{"item": "Data add-on 10GB", "date": "2026-10-12", "amount": 1200}], "base_plan_changed": false}
}
```

### 2b. `POST /auth/login` — step 1 of login

Called by the Orchestrator (with `X-Internal-Key`), never by the browser.

Request: `{"msisdn": "0712345678"}`

| HTTP | Body | Meaning |
| --- | --- | --- |
| 200 | `{"otp_sent": true, "channel": "sms", "expires_in": 300}` | Generic response for both known and unknown numbers. No OTP is returned. |
| 200 | same generic success shape | Unknown numbers are not revealed and no SMS is sent. |
| 400 | `{"detail": "Enter a valid Sri Lankan mobile number"}` | Invalid number format. |
| 200 | same generic response | Delivery failures are logged and the OTP is invalidated without exposing account existence. |
| 429 | `{"detail": "Too many attempts, try again in a minute"}` | Rate limit: 5 per minute per msisdn or IP. |

### 2c. `POST /auth/verify-otp` — step 2 of login

Request: `{"msisdn": "0712345678", "otp": "482913"}`

| HTTP | Body | Meaning |
| --- | --- | --- |
| 200 | `{"token": "<string>", "expires_in": 900}` | The Orchestrator stores `token` in its session. The browser never sees it. |
| 401 | `{"detail": "Code rejected"}` | Wrong code, expired (5 min), or 4th attempt. Same message for all three. |
| 429 | `{"detail": "…"}` | Rate limit. |

The token is **opaque to everyone but you**. It can be your own JWT (HS256,
`sub` = subscriber_id, 15 min) or a token from Supabase Auth. Whatever you
issue, `/handle` must verify it and map it to one subscriber_id.

---

## 3. What the UI does with your reply

- `answer` is shown in the bubble.
- `bill_diff` renders a card: the change in large monospace (amber if up, green if down), each driver with its date and amount, and a green "Base plan unchanged" line when `base_plan_changed` is false.
- `quota` renders a card with "X GB left" and a progress bar from `used_gb / allowance_gb`.
- `needs_auth` makes the UI show a login gate and pulse the account panel.
- The browser never receives or displays an OTP from an API response.

---

## 4. Files and what goes where

```
agents/account_agent/
├── README.md        this guide
├── __main__.py      python -m agents.account_agent
├── main.py          FastAPI app: /health, /auth/login, /auth/verify-otp, /handle. Replace the stub bodies.
├── auth.py          OTP create/verify, token issue/verify, SMS sending (simulated or real)
├── repository.py    read-only data access, parameterised, every query filtered by subscriber_id
├── bill_diff.py     pure Python: this month vs last month → {change, drivers, base_plan_changed}
├── prompts.py       the one phrasing prompt (amounts and descriptions only)
└── examples/        sample envelopes for scripts/ping_agent.py

data/db/schema.sql   tables: plans, subscribers, bills, bill_items, usage, payments (done)
data/db/seed.py      builds the synthetic data (you write this)
data/db/telecare.db  generated (gitignored) if you use SQLite
data/db/auth.db      generated OTP store (gitignored) if you use SQLite
tests/test_bill_diff.py   already written; remove the xfail marker when it passes
docs/security_test_log.md your attack log (you write this)
```

JWT and Fernet live **here** (in `auth.py` and `repository.py`), not in
`shared/`. Nobody else needs them.

---

## 5. Data store: your choice, two paths

The Orchestrator does not care where your data lives. Pick one and document it
in this README's section 10.

**Path A — SQLite (default, zero setup).**
`seed.py` creates `data/db/telecare.db` from `schema.sql`. The agent opens it
with `sqlite3.connect("file:data/db/telecare.db?mode=ro", uri=True)`; any
write raises `OperationalError`. OTP hashes go in a separate writable
`auth.db`.

**Path B — Supabase (Postgres).**
Create the tables from `schema.sql` in your Supabase project. Create a
**SELECT-only database role** for the agent's runtime connection; use the
service role only inside `seed.py`. Keys go in `.env` as `SUPABASE_URL` and
`SUPABASE_KEY` (already in `shared.config.settings`; never commit them, never
send them to the browser). Your read-only proof becomes: attempt an INSERT with
the runtime role and show the permission error. Parameterised queries still
apply (psycopg `%s` or the supabase-py client).

**Both paths must satisfy:** `LLM_PROVIDER=mock pytest -q` passes with no
internet. If you choose Supabase, your tests must use a temporary SQLite file
or in-memory fakes. A good pattern is a `connect()` that returns SQLite when
`SUPABASE_URL` is empty and Postgres when it is set.

---

## 6. OTP delivery: real SMS if configured, simulated fallback

The OTP itself is always yours: 6 digits from `secrets`, hash stored with a
5-minute expiry and a 3-attempt counter. Only the *delivery* changes.
`settings.sms_provider` (from `.env`, default `simulated`):

- `simulated` → development/test only; never returns the OTP and is rejected when `APP_ENV=production`.
- `textit` → send through the Textit.biz REST v1 API using `Authorization: Basic <API key>` and return no debug OTP.
- `http` → send the code through a configurable JSON gateway and return no debug OTP.

**Your gateway.** It is one HTTP call: POST the destination number and the
message text to `settings.sms_gateway_url`, authenticated with
`settings.sms_gateway_key` the way the provider documents (header or body
field), optional `settings.sms_sender_id`. Put the call in one function in
`auth.py`, e.g. `send_sms(msisdn, text) -> bool`, using `httpx` with a short
timeout (5 s). Message text: `"TeleCare: your one-time code is 482913. It expires in 5 minutes."`

Real SMS mode fails closed when the gateway fails, times out, or has no URL.
The API returns the same generic accepted response, invalidates the OTP, and
logs `sms_failed`, preventing delivery outages from becoming enumeration oracles.

Test numbers for real SMS can be team members' own numbers on synthetic
subscriber rows. The gateway key stays in `.env`. The phone number is PII:
mask it in anything that reaches the LLM, and never log the message text.

---

## 7. Run alone, test alone

```bash
pip install bcrypt PyJWT cryptography faker            # + supabase / psycopg if you choose Path B
python data/db/seed.py                                 # build the data
python -m agents.account_agent                         # run only this agent

# from another terminal
python scripts/ping_agent.py account_agent --login 0712345678
python scripts/ping_agent.py account_agent --otp 0712345678 482913        # prints the token
python scripts/ping_agent.py account_agent --intent bill_enquiry --query "why is my bill higher" --token <token>
python scripts/ping_agent.py account_agent --intent bill_enquiry --query "why is my bill higher"   # no token → needs_auth

LLM_PROVIDER=mock pytest tests/test_bill_diff.py tests/contract/test_contract_account.py -q
python run_all.py                                       # full system, log in from the UI
```

---

## 8. Build order (each step has a proof)

1. **seed.py.** 40 Faker subscribers, each with this month and last month's bills and items, usage, a payment. About a third get a deliberate change. **One fixed demo subscriber**: msisdn `0712345678`, a Rs. 1,200 "Data add-on 10GB" dated the 12th of this month, base plan unchanged. Fernet-encrypt the name/email/NIC.
   *Proof:* open the DB; names are ciphertext; the demo row exists.
2. **bill_diff.py.** Compare two bills and their items.
   *Proof:* remove the `xfail` in `tests/test_bill_diff.py`; it passes.
3. **repository.py.** `connect()` read-only; `get_bills`, `get_bill_items`, `get_usage`, `get_plan`, `get_payments`, each taking `subscriber_id` and using `?`/`%s` parameters.
   *Proof:* a write through `connect()` raises; `' OR 1=1 --` as a parameter returns nothing extra.
4. **auth.py — identity lookup.** Normalize the mobile number and use a generic success response so unknown subscribers are not revealed.
5. **auth.py — OTP.** Create (bcrypt hash, expiry, attempts) and verify. Use real HTTP SMS in production.
6. **auth.py — token.** Issue (HS256, `sub`, 15 min, secret from `settings.jwt_secret`) and verify (signature + expiry → subscriber_id or None).
7. **main.py — /auth/login and /auth/verify-otp.** Shapes from section 2. Rate limit 5/min with slowapi.
   *Proof:* `ping_agent.py --login` then `--otp` returns a token; the 6th login in a minute gets 429.
8. **main.py — /handle.** Verify token → subscriber_id → bill_enquiry (bills + items → `bill_diff` → `shared.llm.generate` phrasing with `BILL_EXPLAIN_SYSTEM`, amounts and descriptions only) · quota_check (plan allowance − usage). Return the card data.
   *Proof:* contract test green; the bill card appears in the UI after login.
9. **Real SMS (optional).** Add the `http` channel through your gateway, with the simulated fallback.
10. **Security test log.** Run every attack in section 9 and record blocked / not blocked with screenshots.

---

## 9. Attacks you must run and log (`docs/security_test_log.md`)

| # | Attack | Expected |
| --- | --- | --- |
| 1 | `' OR 1=1 --` in msisdn at login | 400, nothing leaked |
| 2 | SQL in the chat query ("…; DROP TABLE bills") | Parameterised; no effect |
| 3 | Account question with no token (direct call to :8002) | `needs_auth` |
| 4 | Tampered JWT (change one character) | `needs_auth` |
| 5 | Expired JWT | `needs_auth` |
| 6 | Another subscriber's number typed in the message while logged in | `forbidden`; no account lookup or data returned |
| 7 | Request an OTP 6 times in a minute | 429 on the 6th |
| 8 | OTP 4th attempt | 401 |
| 9 | OTP after 5 minutes | 401 |
| 10 | Write to the runtime DB connection | Exception |
| 11 | Direct call to :8002 without `X-Internal-Key` | 401 |
| 12 | Read the DB file / table directly | Names, emails, NICs are ciphertext |
| 13 | Prompt sent to the LLM (mock captures it) | Contains amounts, no phone/name/NIC |
| 14 | `.env` and `*.db` in Git | Absent |
| 15 | SMS gateway down or wrong URL (real SMS) | Generic response, OTP invalidated, `sms_failed` logged |

---

## 10. Your notes (fill in)

- Data store chosen: …
- SMS channel chosen: …
- Demo subscriber: msisdn `0712345678`, passwordless SMS OTP
- How to prove read-only: …

## 11. Definition of done

- [ ] `tests/test_bill_diff.py` passes without the xfail.
- [ ] `pytest tests/contract/test_contract_account.py` passes offline in mock mode.
- [ ] Demo subscriber logs in through the UI (OTP via toast or real SMS), asks the bill question, sees the bill card with Rs. 1,200 and the 12th.
- [ ] All 15 attacks logged with evidence.
- [ ] You can explain every line in this folder at the viva.
