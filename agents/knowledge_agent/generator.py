"""Grounded answer generation with [1], [2] citations.   Owner: M2

    answer(query, chunks, plan_advice=False) -> {"answer": str, "sources": list}

Rules in the prompt: answer only from the numbered chunks, cite as [n], say
"I don't have that information" if they do not cover it. All LLM calls go
through shared.llm.generate.
"""
