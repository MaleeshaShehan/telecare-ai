"""Dense, BM25 and hybrid (RRF) retrieval + the sufficiency judgement.   Owner: M2

Contract used by main.py and eval/run_ir_eval.py:
    dense_search(query, k=10, category=None) -> list[Chunk]
    bm25_search(query, k=10, category=None)  -> list[Chunk]
    hybrid_search(query, k=4, category=None) -> list[Chunk]   # RRF, score = sum 1/(60+rank)
    is_sufficient(chunks) -> bool   # best cosine >= settings.retrieval_min_similarity

Chunk = dict with: chunk_id, doc_id, title, source_url, category, text, score
"""
