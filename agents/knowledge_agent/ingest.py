"""Offline ingest: load -> clean -> chunk -> embed -> index.   Owner: M2

Run:  python -m agents.knowledge_agent.ingest
Rerun whenever data/corpus changes.

Steps (BUILD_PLAN section 6):
1. Load each file in data/corpus/manifest.csv (pypdf / python-docx / bs4 / plain).
2. Clean and save to data/corpus/processed/<doc_id>.md.
3. Chunk ~400 tokens, ~60 overlap; each tariff-table row is its own chunk.
4. Attach metadata: doc_id, title, category, operator, source_url, chunk_id.
5. Embed with all-MiniLM-L6-v2 -> ChromaDB (cosine) at data/chroma/.
6. Build BM25 over the same chunks -> data/bm25.pkl.
"""


def main() -> None:
    raise NotImplementedError("M2: see docstring")


if __name__ == "__main__":
    main()
