"""IR evaluation: P@3, Recall@5, MRR for bm25 / dense / hybrid.   Owner: M2

    python eval/run_ir_eval.py

Reads eval/ir_testset.jsonl, one line per question:
    {"q": "cheapest 5GB anytime package", "doc_id": "D001"}
Writes eval/results/ir_eval.csv and a bar chart.

Write the questions from the documents BEFORE tuning anything, and do not
change them afterwards.
"""


def main() -> None:
    raise NotImplementedError("M2")


if __name__ == "__main__":
    main()
