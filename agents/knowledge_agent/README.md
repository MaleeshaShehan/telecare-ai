# Knowledge Agent — builder guide

Port **8001** · Endpoint **POST /handle** · Owner: you, end to end.

You are building the Information Retrieval module, the part of the course that
carries the most marks. You do not need to touch the Orchestrator, the UI, or
anything in `shared/`. Everything you need to plug in is in this file.

---

## 1. What this agent is

The **product expert** of the care desk. It owns the operator's public documents
(package and tariff sheets, roaming and coverage notices, troubleshooting
guides, FAQs) and answers questions from them with citations. It never answers
from the model's memory. If the documents do not cover the question, it says
so with `not_found` and the Orchestrator offers a human.

Decisions this agent makes on its own (this is what makes it an agent):
is the retrieved evidence good enough, should it rewrite the query and search
again, should it answer or admit it does not know.

---

## 2. The contract (what arrives, what you must return)

The Orchestrator has already classified the intent and extracted entities.
You receive one `Envelope` and return one `Envelope`. Use the helpers in
`shared/envelope.py`; never build the dict by hand.

**Intents routed to you** (from `shared/intents.py`):

| intent | Typical question | Category filter you should apply |
| --- | --- | --- |
| package_info | "What does Anytime 5GB include?" | none |
| tariff_query | "How much is 10GB?" | none |
| roaming_advice | "Roaming rates for India?" | `roaming` |
| coverage_or_outage_info | "Is there an outage in Kandy?" | `coverage` |
| troubleshooting | "My data is slow after the update" | `troubleshooting` |
| plan_advice | "I stream video every evening, what plan suits me?" | `package` |

The mapping is in `shared.intents.INTENT_CATEGORY`. Import it, do not copy it.

**Request you receive:**

```json
{
  "message_id": "…", "conversation_id": "…",
  "sender_agent": "orchestrator", "receiver_agent": "knowledge_agent",
  "intent": "plan_advice",
  "payload": {
    "query": "I mostly stream video at home in the evenings, what plan suits me?",
    "entities": {"phone": [], "amount": [], "date": [], "country": null,
                 "package_name": null, "data_amount": null}
  },
  "auth_token": null,
  "timestamp": "2026-10-08T10:15:00Z"
}
```

`auth_token` is always `null` for you. Knowledge questions never need login.

**Reply you must return** — `make_reply(env, status, result)`:

| status | When | `result` keys |
| --- | --- | --- |
| `ok` | Evidence was sufficient and you generated an answer | `answer: str` with `[1]`, `[2]` citations · `sources: list[{id:int, title:str, url:str, chunk_id:str}]` |
| `not_found` | Evidence too weak after your retry | `reason: str` (e.g. `"retrieval_insufficient best_score=0.21"`) |
| `error` | Something broke (index missing, LLM failed) | `reason: str` |

Never return `needs_auth` or `escalate` from this agent.

Example `ok` payload:

```json
{
  "status": "ok",
  "answer": "For evening video streaming, Home Streamer 100GB fits best [1]. It includes 100GB with no peak-hour limit [1] and costs Rs. 2,490 a month [2]. This is a suggestion; check the details before switching.",
  "sources": [
    {"id": 1, "title": "Home Broadband Packages", "url": "https://www.dialog.lk/home-broadband", "chunk_id": "D004-3"},
    {"id": 2, "title": "Home Broadband Tariffs", "url": "https://www.dialog.lk/home-broadband/tariffs", "chunk_id": "D005-1"}
  ]
}
```

The header `X-Internal-Key` is checked for you by `Depends(require_internal_key)`
in `main.py`. Leave it there.

---

## 3. What the UI does with your reply

- `answer` is rendered with `**bold**` and line breaks. Every `[n]` becomes a
  clickable chip that highlights source `n`.
- `sources` become cards under the answer, numbered by `id`, title bold, URL
  grey, `chunk_id` small on the right. **`id` must match the `[n]` in the text.**
- On `not_found` the UI shows your reason to nobody; the user sees a friendly
  message and a "Talk to a human" button. Put the detail in the reason for the
  audit log.

---

## 4. Files in this folder and what goes where

```
agents/knowledge_agent/
├── README.md        this guide
├── __main__.py      python -m agents.knowledge_agent  (runs only this agent)
├── main.py          FastAPI app. Replace the body of handle(). Keep /health and the key check.
├── ingest.py        OFFLINE. load → clean → chunk → embed → Chroma + BM25. Run after corpus changes.
├── retriever.py     dense_search, bm25_search, hybrid_search (RRF), is_sufficient
├── generator.py     grounded answer + citations via shared.llm.generate
├── prompts.py       system prompts (grounded, plan advice, query rewrite)
└── examples/        sample request envelopes for scripts/ping_agent.py

data/corpus/raw/          the documents you collect (PDF, HTML, DOCX, MD)
data/corpus/processed/    cleaned markdown, one file per document (committed, human-checkable)
data/corpus/manifest.csv  one row per document: doc_id,file,title,category,operator,source_url,retrieved_on
data/chroma/              generated vector store (gitignored)
data/bm25.pkl             generated BM25 index (gitignored)
eval/ir_testset.jsonl     your ~25 test questions {"q": "...", "doc_id": "D001"}
eval/run_ir_eval.py       P@3, Recall@5, MRR for bm25 / dense / hybrid
```

Function signatures are in each file's docstring. Keep them: `main.py` and the
eval script call them.

---

## 5. Shared helpers you use, files you must not edit

Use:

- `shared.envelope.Envelope`, `make_reply`
- `shared.intents.Intent`, `INTENT_CATEGORY`
- `shared.llm.generate(system, prompt, json_schema=None, temperature=0.2)` — the only way to call an LLM. It masks PII, uses Gemini and falls back to GPT per `.env`, and returns canned text when `LLM_PROVIDER=mock`.
- `shared.config.settings.retrieval_min_similarity` — your sufficiency threshold, from `.env`
- `shared.audit.log_decision(conversation_id, "knowledge_agent", decision, reason)` — log `retrieved`, `retrieval_insufficient`, `query_rewritten`, `answered`. Never log the query text.
- `shared.http.require_internal_key`

Do **not** edit: anything in `shared/`, `agents/orchestrator/`, `agents/account_agent/`,
`agents/supervisor_agent/`, `ui/`, `tests/contract/`. If you need a change there, tell the lead.

---

## 6. Run alone, test alone

```bash
# install your libraries (once)
pip install sentence-transformers chromadb rank-bm25 pypdf python-docx beautifulsoup4
# Windows, if torch is slow: pip install torch --index-url https://download.pytorch.org/whl/cpu

# build indexes after the corpus changes
python -m agents.knowledge_agent.ingest

# run only your agent (auto-reloads on save)
python -m agents.knowledge_agent

# send it exactly what the Orchestrator would send, from another terminal
python scripts/ping_agent.py knowledge_agent --intent package_info --query "cheapest 5GB anytime package"
python scripts/ping_agent.py knowledge_agent --file agents/knowledge_agent/examples/plan_advice.json

# your definition of done
LLM_PROVIDER=mock pytest tests/contract/test_contract_knowledge.py -q

# the whole system, with the other agents as stubs
python run_all.py
```

The ping script validates your reply shape and prints it. Use it instead of
the UI while developing: the UI goes through the Orchestrator's intent
classifier, which may route your test phrase elsewhere.

**Offline rule:** `LLM_PROVIDER=mock pytest -q` must pass with no internet and
no API key. Retrieval is local anyway. For generation, mock mode returns the
string `MOCK_REPLY`; your code must accept that and still return a valid `ok`
envelope.

---

## 7. Build order (each step has a proof)

1. **Corpus.** 20–40 public documents into `data/corpus/raw/`, row per document in `manifest.csv`. Aim: 8+ package/tariff, 4+ roaming, 3+ coverage/outage, 6+ troubleshooting, 3+ FAQ, 2+ policy. Add a one-line "best for…" to every package page so plan advice has something to match. Only public operator material.
   *Proof:* manifest has ≥ 20 rows, every file exists.
2. **IR test questions, before any tuning.** ~25 questions with the doc_id that answers each into `eval/ir_testset.jsonl`. Do not change them afterwards.
   *Proof:* file has ≥ 25 lines.
3. **Load + clean.** `ingest.py` reads each manifest row by file type, strips headers/footers/nav, normalises whitespace, writes `processed/<doc_id>.md`.
   *Proof:* open two processed files and read them; they look like clean articles.
4. **Chunk.** Headings and paragraphs first, then ~400 tokens with ~60 overlap. **Every tariff-table row becomes its own chunk**, prefixed with the package name and column headers, so "Anytime 5GB costs Rs. 999" is one retrievable unit. Attach `doc_id, title, category, operator, source_url, chunk_id`.
   *Proof:* print 5 chunks; a tariff row reads as a sentence.
5. **Embed + index.** `all-MiniLM-L6-v2`, normalised, Chroma persistent collection with cosine. BM25 over the same chunks (lowercase tokens; keep numbers like `1000`, `5gb`) to `bm25.pkl`.
   *Proof:* `python -m agents.knowledge_agent.ingest` finishes; `data/chroma/` exists.
6. **dense_search / bm25_search.** Top-10 each, optional category filter.
   *Proof:* in a REPL, the right doc appears in top-3 for 3 test questions.
7. **hybrid_search.** Reciprocal Rank Fusion: `score = Σ 1/(60 + rank)`. Keep top 4.
   *Proof:* `eval/run_ir_eval.py` runs for all three configs and hybrid is best or equal.
8. **is_sufficient.** Best cosine ≥ `settings.retrieval_min_similarity` (start 0.35, tune on the test set).
   *Proof:* a nonsense query returns `not_found`; a real one returns `ok`.
9. **generator.** Prompt with the 4 numbered chunks; rules: answer only from them, cite `[n]`, say "I don't have that information" if not covered. Plan advice uses `PLAN_ADVICE_SYSTEM` and ends with the suggestion disclaimer.
   *Proof:* with a real key, the answer cites the right source; with mock, the envelope is still valid.
10. **Wire main.py.** Category filter → hybrid → sufficiency → (Should: one LLM query rewrite and retry) → generate or `not_found`. Log each decision.
    *Proof:* `pytest tests/contract/test_contract_knowledge.py` green; "cheapest 5GB" returns a cited answer in the UI.
11. **Evaluation.** `run_ir_eval.py` writes `eval/results/ir_eval.csv` and a bar chart. This table goes in the report.

---

## 8. Rules that apply to you (Responsible AI)

- Answer **only** from retrieved chunks. Never let the model fill gaps.
- Every factual sentence carries a citation.
- Plan advice is a suggestion from package descriptions, not a cost calculation. Say so in the answer.
- Log decisions, not queries.
- All documents are public operator material. No customer data in the corpus.

---

## 9. Definition of done

- [ ] `pytest tests/contract/test_contract_knowledge.py` passes in mock mode, offline.
- [ ] "What is the cheapest 5GB anytime package?" returns a correct, cited answer in the UI with a real LLM key.
- [ ] A nonsense question returns `not_found` and the UI offers a human.
- [ ] `eval/results/ir_eval.csv` exists with P@3, Recall@5, MRR for bm25, dense, hybrid.
- [ ] You can explain every line in this folder at the viva.
