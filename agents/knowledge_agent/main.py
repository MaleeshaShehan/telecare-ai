"""Telecom Knowledge Agent :8001 - RAG over data/corpus (the IR module).   Owner: M2

POST /handle  Envelope -> Envelope   (requires X-Internal-Key)
GET  /health

Today returns a stub `ok` answer so the orchestrator and UI run end to end.
TODO(M2): replace the body of handle() with retriever + generator:
    chunks = retriever.hybrid_search(query, category=INTENT_CATEGORY.get(intent))
    if retriever.is_sufficient(chunks): answer = generator.answer(query, chunks)
    else: return make_reply(env, "not_found", {"reason": "retrieval_insufficient"})
"""
from fastapi import Depends, FastAPI

from shared.audit import log_decision
from shared.envelope import Envelope, make_reply
from shared.http import require_internal_key

app = FastAPI(title="TeleCare Knowledge Agent")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "knowledge_agent"}


@app.post("/handle", dependencies=[Depends(require_internal_key)])
def handle(env: Envelope) -> Envelope:
    log_decision(env.conversation_id, "knowledge_agent", "stub_answer", f"intent={env.intent.value}")
    return make_reply(env, "ok", {
        "answer": f"[stub] Knowledge Agent received intent '{env.intent.value}'. Real RAG answer coming from M2. [1]",
        "sources": [{"id": 1, "title": "stub document", "url": "https://example.invalid", "chunk_id": "D000-0"}],
    })
