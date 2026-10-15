"""
Ask Fork latency benchmark.

Asks a set of real questions against a real calculation and reports, per
question, the total wait and each model call inside it (from the
Server-Timing header), whether the answer came from the grounded model
or the deterministic fallback, and whether it was a cache hit.

    cd backend
    set ANTHROPIC_API_KEY=sk-ant-...          (PowerShell: $env:ANTHROPIC_API_KEY="...")
    py scripts/bench_ask_fork.py
    py scripts/bench_ask_fork.py --intent-model claude-haiku-4-5   # try a faster classifier
    py scripts/bench_ask_fork.py --repeat 2                        # second round shows cache hits

--simulate runs without a key: every model call sleeps for a time modelled
from its prompt size and a typical output length. Those numbers are an
estimate of the shape of the wait, not a measurement.
"""

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QUESTIONS = [
    # Suggestion chips -- answered without the classifier.
    "Explain the biggest difference",
    "Break down the additional cost",
    "Why will graduation take longer?",
    "Compare the career outlook",
    "What does this data not tell me?",
    # Typed questions -- classifier, then explanation.
    "how much more would switching cost me in total?",
    "is it worth it if I care most about salary?",
    "how many of my credits would I lose?",
    "what if I only care about finishing fast?",
    "explain this like I'm a first-gen student",
]

BODY = {
    "current_major": "computer_science",
    "prospective_major": "business_administration",
    "credits_completed": 72,
    "credits_transferable": 60,
    "credits_in_progress": 15,
}

# Modelled rates for --simulate (seconds). Deliberately round numbers.
FIRST_TOKEN_BASE = 0.8
FIRST_TOKEN_PER_1K_INPUT = 0.12
OUTPUT_TOKENS_PER_SECOND = 60
TYPICAL_OUTPUT_TOKENS = {"intent": 90, "explain": 550}


def simulate():
    import ai.interface as ai
    from tests.test_main import _GOOD_EXPLAIN_JSON

    intent = json.dumps({"topic_scope": "financial"})

    def fake(system, user_message, max_tokens=1024, model=None):
        kind = "intent" if system.startswith("You interpret one message") else "explain"
        input_tokens = (len(system) + len(user_message)) / 4
        cached = os.environ.get("BENCH_CACHED_SYSTEM") == "1"
        prompt_tokens = (len(user_message) / 4) if cached else input_tokens
        wait = (
            FIRST_TOKEN_BASE
            + FIRST_TOKEN_PER_1K_INPUT * prompt_tokens / 1000
            + TYPICAL_OUTPUT_TOKENS[kind] / OUTPUT_TOKENS_PER_SECOND
        )
        time.sleep(wait)
        return intent if kind == "intent" else _GOOD_EXPLAIN_JSON

    ai._call_model = fake


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--intent-model")
    parser.add_argument("--explanation-model")
    args = parser.parse_args()

    if args.intent_model:
        os.environ["FORK_INTENT_MODEL"] = args.intent_model
    if args.explanation_model:
        os.environ["FORK_EXPLANATION_MODEL"] = args.explanation_model
    if not args.simulate and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY, or pass --simulate for a modelled estimate.")

    from fastapi.testclient import TestClient

    import ai.interface as ai
    import main as app_module

    if args.simulate:
        simulate()
    print(
        f"intent model: {ai.INTENT_MODEL}   explanation model: {ai.EXPLANATION_MODEL}"
        f"{'   (SIMULATED timings)' if args.simulate else ''}\n"
    )

    client = TestClient(app_module.app)
    rows = []
    for round_ in range(1, args.repeat + 1):
        for q in QUESTIONS:
            start = time.perf_counter()
            res = client.post("/decision-paths/change-major/explain", json={**BODY, "question": q})
            total = time.perf_counter() - start
            data = res.json()
            rows.append(
                {
                    "round": round_,
                    "question": q,
                    "total": total,
                    "status": data.get("status"),
                    "fallback": data.get("used_fallback"),
                    "cache": res.headers.get("X-Fork-Answer-Cache") == "hit",
                    "timing": res.headers.get("Server-Timing", ""),
                }
            )
            r = rows[-1]
            flag = "cache" if r["cache"] else ("FALLBACK" if r["fallback"] else r["status"])
            print(f"{total:6.2f}s  {flag:<10} {q[:46]:<46}  {r['timing']}")

    totals = [r["total"] for r in rows if not r["cache"]]
    if totals:
        print(
            f"\nuncached: n={len(totals)}  median {statistics.median(totals):.2f}s  "
            f"max {max(totals):.2f}s  fallbacks {sum(1 for r in rows if r['fallback'])}"
        )
    hits = [r["total"] for r in rows if r["cache"]]
    if hits:
        print(f"cached:   n={len(hits)}  median {statistics.median(hits):.3f}s")


if __name__ == "__main__":
    main()
