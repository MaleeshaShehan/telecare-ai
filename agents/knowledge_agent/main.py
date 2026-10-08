"""Telecom Knowledge Agent :8001 - RAG over data/corpus (the IR module).   Owner: M2

POST /handle  Envelope -> Envelope   (requires X-Internal-Key)
GET  /health
"""
from fastapi import Depends, FastAPI

from agents.knowledge_agent import generator, retriever
from shared.audit import log_decision
from shared.envelope import Envelope, make_reply
from shared.http import require_internal_key
from shared.intents import INTENT_CATEGORY, Intent

app = FastAPI(title="TeleCare Knowledge Agent")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": "knowledge_agent"}


@app.post("/handle", dependencies=[Depends(require_internal_key)])
def handle(env: Envelope) -> Envelope:
    payload = env.payload or {}
    query = payload.get("query")
    if not query or not str(query).strip():
        log_decision(env.conversation_id, "knowledge_agent", "retrieval_insufficient", "best_score=0.0")
        return make_reply(env, "not_found", {"reason": "retrieval_insufficient best_score=0.0"})

    query_str = str(query).strip()

    try:
        category = INTENT_CATEGORY.get(env.intent)
        chunks = retriever.hybrid_search(query_str, k=4, category=category)

        # Audit filter_retry if category relaxation occurred
        filter_retried = any(c.get("filter_relaxed") for c in chunks) or (category is not None and not chunks)
        if filter_retried:
            log_decision(env.conversation_id, "knowledge_agent", "filter_retry", f"category={category}")

        best_score = max(
            (c.get("dense_similarity", c.get("score", 0.0)) for c in chunks),
            default=0.0,
        )
        log_decision(
            env.conversation_id,
            "knowledge_agent",
            "retrieved",
            f"count={len(chunks)} best_score={best_score:.4f}",
        )

        if not retriever.is_sufficient(chunks):
            log_decision(
                env.conversation_id,
                "knowledge_agent",
                "retrieval_insufficient",
                f"best_score={best_score:.4f}",
            )
            return make_reply(
                env,
                "not_found",
                {"reason": f"retrieval_insufficient best_score={best_score:.4f}"},
            )

        is_plan_advice = (env.intent == Intent.PLAN_ADVICE)
        gen_result = generator.answer(query_str, chunks, plan_advice=is_plan_advice)

        if gen_result.get("status") == "not_found":
            reason = gen_result.get("reason", "declined_by_generator")
            log_decision(env.conversation_id, "knowledge_agent", "declined", f"reason={reason}")
            return make_reply(env, "not_found", {"reason": reason})

        log_decision(
            env.conversation_id,
            "knowledge_agent",
            "answered",
            f"sources={len(gen_result.get('sources', []))} plan_advice={is_plan_advice}",
        )
        return make_reply(env, "ok", {
            "answer": gen_result["answer"],
            "sources": gen_result.get("sources", []),
        })

    except Exception as exc:
        log_decision(env.conversation_id, "knowledge_agent", "error", f"reason={type(exc).__name__}")
        return make_reply(env, "error", {"reason": f"{type(exc).__name__}: {exc}"})
