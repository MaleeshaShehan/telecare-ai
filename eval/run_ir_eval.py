"""IR evaluation: Hit@3, P@3, Recall@5, MRR for BM25 / Dense / Hybrid.   Owner: M2

Usage:
    python eval/run_ir_eval.py

Reads eval/ir_testset.jsonl (25 positives + 3 negative controls).
Outputs:
    eval/results/ir_eval.csv
    eval/results/ir_eval.png
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib.pyplot as plt

from agents.knowledge_agent.retriever import (
    bm25_search,
    dense_search,
    hybrid_search,
)
from shared.config import settings

TESTSET_PATH = REPO_ROOT / "eval" / "ir_testset.jsonl"
RESULTS_DIR = REPO_ROOT / "eval" / "results"
CSV_PATH = RESULTS_DIR / "ir_eval.csv"
CHART_PATH = RESULTS_DIR / "ir_eval.png"


def load_testset() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load test cases into positives and negative controls."""
    positives: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []

    with open(TESTSET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item.get("negative") is True:
                negatives.append(item)
            else:
                positives.append(item)

    return positives, negatives


def is_chunk_relevant(chunk: dict[str, Any], query_spec: dict[str, Any]) -> bool:
    """Check relevance according to ref_id / also_ok or guide gold_snippet."""
    gold_snippet = query_spec.get("gold_snippet")
    if gold_snippet:
        target_doc = query_spec.get("doc_id")
        return chunk.get("doc_id") == target_doc and gold_snippet in chunk.get("text", "")

    target_ref = query_spec.get("ref_id")
    also_ok = query_spec.get("also_ok") or []
    c_ref = chunk.get("ref_id")
    return c_ref == target_ref or c_ref in also_ok


def dedupe_by_ref_id(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate retrieved chunks by ref_id preserving highest-ranked occurrence."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for c in chunks:
        ref = c.get("ref_id") or c.get("chunk_id")
        if ref not in seen:
            seen.add(ref)
            deduped.append(c)
    return deduped


def evaluate_mode(mode: str, positives: list[dict[str, Any]], k: int = 5) -> dict[str, float]:
    """Compute Hit@3, P@3, Recall@5, MRR for a retrieval mode."""
    hit_at_3_list: list[float] = []
    p_at_3_list: list[float] = []
    recall_at_5_list: list[float] = []
    mrr_list: list[float] = []

    for item in positives:
        q = item["q"]
        if mode == "bm25":
            raw_hits = bm25_search(q, k=k * 2)
        elif mode == "dense":
            raw_hits = dense_search(q, k=k * 2)
        elif mode == "hybrid":
            raw_hits = hybrid_search(q, k=k * 2)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        hits = dedupe_by_ref_id(raw_hits)[:k]

        rel_flags = [is_chunk_relevant(c, item) for c in hits]

        # Total relevant targets for this query
        also_ok = item.get("also_ok") or []
        total_rel = 1.0 + len(also_ok) if not item.get("gold_snippet") else 1.0

        # Hit@3
        hit_3 = 1.0 if any(rel_flags[:3]) else 0.0
        hit_at_3_list.append(hit_3)

        # P@3
        p_3 = sum(rel_flags[:3]) / 3.0
        p_at_3_list.append(p_3)

        # Recall@5
        rec_5 = min(1.0, sum(rel_flags[:5]) / total_rel)
        recall_at_5_list.append(rec_5)

        # MRR
        mrr = 0.0
        for rank, is_rel in enumerate(rel_flags, start=1):
            if is_rel:
                mrr = 1.0 / rank
                break
        mrr_list.append(mrr)

    n = len(positives)
    return {
        "Hit@3": sum(hit_at_3_list) / n,
        "P@3": sum(p_at_3_list) / n,
        "Recall@5": sum(recall_at_5_list) / n,
        "MRR": sum(mrr_list) / n,
    }


def evaluate_negatives(negatives: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    """Evaluate negative controls for false-answer rate at threshold."""
    results: list[dict[str, Any]] = []
    false_answers = 0
    threshold = settings.retrieval_min_similarity

    for item in negatives:
        q = item["q"]
        hits = dense_search(q, k=5)
        best_dense = max((c.get("dense_similarity", c.get("score", 0.0)) for c in hits), default=0.0)
        passes = best_dense >= threshold
        if passes:
            false_answers += 1
        results.append({
            "q": q,
            "best_dense_similarity": best_dense,
            "passes_threshold": passes,
        })

    rate = (false_answers / len(negatives)) * 100.0 if negatives else 0.0
    return results, rate


def save_chart(metrics: dict[str, dict[str, float]]) -> None:
    """Generate bar chart comparing BM25, Dense, and Hybrid."""
    modes = list(metrics.keys())
    metric_names = ["Hit@3", "P@3", "Recall@5", "MRR"]

    x = range(len(metric_names))
    width = 0.25

    fig, ax = plt.subplots(figsize=(9, 5))

    for i, mode in enumerate(modes):
        scores = [metrics[mode][m] for m in metric_names]
        pos = [p + i * width for p in x]
        bars = ax.bar(pos, scores, width=width, label=mode.upper())
        for bar in bars:
            height = bar.get_height()
            ax.annotate(
                f"{height:.3f}",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ax.set_title("TeleCare IR Evaluation: Retrieval Performance by Mode", fontsize=13, fontweight="bold")
    ax.set_ylabel("Score (0.0 - 1.0)", fontsize=11)
    ax.set_xticks([p + width for p in x])
    ax.set_xticklabels(metric_names, fontsize=10)
    ax.set_ylim(0, 1.15)
    ax.legend(loc="upper left")
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    plt.tight_layout()
    plt.savefig(CHART_PATH, dpi=200)
    plt.close()


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    positives, negatives = load_testset()

    print(f"Loaded {len(positives)} positive test questions and {len(negatives)} negative controls.\n")

    modes = ["bm25", "dense", "hybrid"]
    metrics: dict[str, dict[str, float]] = {}

    for mode in modes:
        metrics[mode] = evaluate_mode(mode, positives, k=5)

    # 1. Print Positives Table
    print("=" * 68)
    print(f"{'Retrieval Mode':<15} | {'Hit@3':<10} | {'P@3':<10} | {'Recall@5':<10} | {'MRR':<10}")
    print("-" * 68)
    for mode in modes:
        m = metrics[mode]
        print(f"{mode.upper():<15} | {m['Hit@3']:<10.4f} | {m['P@3']:<10.4f} | {m['Recall@5']:<10.4f} | {m['MRR']:<10.4f}")
    print("=" * 68)

    # 2. Write CSV
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["mode", "hit_at_3", "p_at_3", "recall_at_5", "mrr"])
        for mode in modes:
            m = metrics[mode]
            writer.writerow([mode, f"{m['Hit@3']:.4f}", f"{m['P@3']:.4f}", f"{m['Recall@5']:.4f}", f"{m['MRR']:.4f}"])

    print(f"\nSaved CSV results to: {CSV_PATH}")

    # 3. Generate Chart
    save_chart(metrics)
    print(f"Saved bar chart to: {CHART_PATH}\n")

    # 4. Evaluate Negatives
    neg_results, false_rate = evaluate_negatives(negatives)
    threshold = settings.retrieval_min_similarity
    print("=" * 68)
    print("NEGATIVE / OUT-OF-CORPUS CONTROLS EVALUATION")
    print(f"Threshold: {threshold} (settings.retrieval_min_similarity)")
    print("-" * 68)
    for nr in neg_results:
        verdict = "REJECTED (Correct)" if not nr["passes_threshold"] else "FALSE ACCEPT (Risk)"
        print(f"Query: \"{nr['q']}\"")
        print(f"  Best Dense Similarity: {nr['best_dense_similarity']:.4f} -> {verdict}")
    print("-" * 68)
    print(f"False-Answer Rate: {false_rate:.1f}% ({sum(1 for nr in neg_results if nr['passes_threshold'])}/{len(neg_results)} negatives passed threshold)")
    print("=" * 68)


if __name__ == "__main__":
    main()
