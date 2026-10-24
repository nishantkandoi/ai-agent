"""
Evaluate the IPL agent against the answer key in evals/questions.json.

For each question: run the gold SQL for the expected rows, ask the agent, then have a
judge model decide whether the agent's answer matches. Prints a summary and saves the run
to evals/results/ (full detail as JSON, one line per run in history.csv).

Run:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/workshop-user-key.json
    .venv/bin/python eval.py              # all questions
    .venv/bin/python eval.py --only q01,q08
"""

import argparse
import csv
import json
import subprocess
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

import agent

# Stronger than the agent's model. On this project it is only served from "global".
JUDGE_MODEL = "gemini-3.1-pro-preview"
JUDGE_LOCATION = "global"
judge_client = genai.Client(vertexai=True, project=agent.PROJECT, location=JUDGE_LOCATION)
EVAL_DIR = Path(__file__).parent / "evals"
RESULTS_DIR = EVAL_DIR / "results"


def judge(item, expected_rows, reply):
    prompt = f"""You are grading an AI agent that answers questions about IPL cricket data.

Question: {item['question']}

Correct result from the database (JSON rows; null means no query exists):
{json.dumps(expected_rows, default=str)}

Reference answer written when the test was approved: {item['expected_answer']}
Test notes: {item['notes'] or '(none)'}

Agent's answer:
{reply}

Grading rules:
- Judge against the database result; the reference answer is only a guide.
- Correct only if the key facts (names, numbers, teams) match. Small rounding or
  formatting differences are fine. Extra correct detail is fine.
- For a question the data cannot answer, it is correct only if the agent says it can't
  answer or the data doesn't cover it, without inventing a figure.

Reply with JSON: {{"correct": true or false, "reason": "one short sentence"}}"""
    start = time.perf_counter()
    resp = judge_client.models.generate_content(
        model=JUDGE_MODEL, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"))
    verdict = json.loads(resp.text)
    usage = resp.usage_metadata
    return bool(verdict["correct"]), str(verdict.get("reason", "")), {
        "judge_s": time.perf_counter() - start,
        "judge_tokens": (usage.total_token_count or 0) if usage else 0,
    }


def evaluate(item, schema):
    result = {k: item[k] for k in ("id", "category", "question", "gold_sql", "expected_answer")}
    result.update(expected_rows=None, reply=None, sql=None, stats=None,
                  correct=False, reason="", judge=None, error=None)
    try:
        if item["gold_sql"]:
            result["expected_rows"] = agent.run_query(item["gold_sql"], agent.new_stats())
        stats = agent.new_stats()
        start = time.perf_counter()
        reply, sql, _ = agent.answer(item["question"], schema, [], stats)
        stats["total_s"] = time.perf_counter() - start
        result.update(reply=reply, sql=sql, stats=stats)
        result["correct"], result["reason"], result["judge"] = judge(
            item, result["expected_rows"], reply)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        result["reason"] = "error: " + result["error"]
    return result


def summarize(results):
    n = len(results)
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["correct"])
    timed = [r["stats"] for r in results if r["stats"]]
    return {
        "n": n,
        "accuracy": sum(r["correct"] for r in results) / n if n else 0,
        "by_category": {c: round(sum(v) / len(v), 3) for c, v in by_cat.items()},
        "avg_time_s": round(sum(s["total_s"] for s in timed) / len(timed), 2) if timed else None,
        "avg_tokens": round(sum(s["tokens_total"] for s in timed) / len(timed)) if timed else None,
    }


def print_report(results, summary):
    print(f"\n{'id':<5}{'category':<14}{'ok':<4}{'time':>7}{'tokens':>9}  reason")
    for r in results:
        s = r["stats"] or {}
        t = f"{s['total_s']:.1f}s" if s else "-"
        tok = f"{s['tokens_total']:,}" if s else "-"
        print(f"{r['id']:<5}{r['category']:<14}{'✓' if r['correct'] else '✗':<4}{t:>7}{tok:>9}  {r['reason']}")
    print(f"\nAccuracy: {summary['accuracy']:.0%} ({sum(r['correct'] for r in results)}/{summary['n']})")
    for c, a in summary["by_category"].items():
        print(f"  {c:<14}{a:.0%}")
    print(f"Avg per question: {summary['avg_time_s']}s, {summary['avg_tokens']} tokens")


def save(results, summary):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, cwd=Path(__file__).parent).stdout.strip()
    except OSError:
        commit = ""
    run = {"timestamp": now.isoformat(timespec="seconds"), "commit": commit,
           "agent_model": agent.MODEL, "judge_model": JUDGE_MODEL,
           "summary": summary, "results": results}
    path = RESULTS_DIR / f"{now:%Y-%m-%d_%H%M}.json"
    path.write_text(json.dumps(run, indent=2, default=str))

    history = RESULTS_DIR / "history.csv"
    new = not history.exists()
    with history.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "commit", "n", "accuracy", "by_category",
                        "avg_time_s", "avg_tokens", "results_file"])
        w.writerow([run["timestamp"], commit, summary["n"], round(summary["accuracy"], 3),
                    json.dumps(summary["by_category"]), summary["avg_time_s"],
                    summary["avg_tokens"], path.name])
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", help="comma-separated question ids, e.g. q01,q08")
    args = parser.parse_args()

    items = json.loads((EVAL_DIR / "questions.json").read_text())
    if args.only:
        wanted = set(args.only.split(","))
        items = [i for i in items if i["id"] in wanted]

    print("Loading schema...")
    schema = agent.load_schema()
    results = []
    for item in items:
        print(f"  {item['id']}: {item['question']}")
        results.append(evaluate(item, schema))

    summary = summarize(results)
    print_report(results, summary)
    print(f"\nSaved: {save(results, summary)}")


if __name__ == "__main__":
    main()
