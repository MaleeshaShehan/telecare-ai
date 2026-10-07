"""Intent classification accuracy + confusion matrix.   Owner: M1 (measures the Orchestrator's NLU)

    python eval/run_intent_eval.py

Reads eval/intent_testset.jsonl, one line per message (include Sri Lankan English phrasing):
    {"text": "machan my data finished already, how to top up?", "intent": "quota_check"}
Writes eval/results/intent_eval.csv and a confusion matrix image.
"""


def main() -> None:
    raise NotImplementedError("M4")


if __name__ == "__main__":
    main()
