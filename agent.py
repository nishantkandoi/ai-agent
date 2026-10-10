"""
ai-agent: ask questions about the IPL warehouse in plain English.

Flow per question: Gemini writes BigQuery SQL from the schema -> dry-run check
-> run (read-only, byte-capped) -> retry on error -> Gemini explains the result.

Setup:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/workshop-user-key.json
    .venv/bin/python agent.py
"""

import json
import re
import time
import warnings

warnings.filterwarnings("ignore")

from google import genai
from google.cloud import bigquery

PROJECT = "ipl-nao"
VERTEX_LOCATION = "us-central1"
BQ_LOCATION = "asia-south1"
MODEL = "gemini-2.5-flash"
DATASET = "ipl_db"
MAX_BYTES = 100 * 1024 * 1024  # 100 MB cap per query
MAX_ROWS = 200                 # rows sent back to the model
MAX_ATTEMPTS = 3

# Things the raw schema doesn't tell the model.
DATA_NOTES = """
- match_date in ipl_batter_match_stats / ipl_bowler_match_stats is INTEGER epoch
  NANOSECONDS: use DATE(TIMESTAMP_MICROS(DIV(match_date, 1000))).
- season is a STRING with irregular values: '2007/08' (= 2008), '2009', '2009/10' (= 2010),
  '2011'..'2019', '2020/21' (= 2020), '2021'..'2026'. For year filters prefer
  match_info_v2.season_start_year or EXTRACT(YEAR FROM the match date).
- Prefer match_info_v2 over ipl_match_info (cleaner types, has home/away team).
- match_info_v2.date is a STRING 'YYYY-MM-DD'.
- Join per-player stats to matches on match_id; players on player_id.
- One row in *_match_stats = one player in one match innings. Aggregate for careers.
- Team names are already normalised to current names (Delhi Capitals, Punjab Kings,
  Royal Challengers Bengaluru), including for older seasons.
- Player names are short scorecard style (e.g. 'V Kohli', 'MS Dhoni', 'RG Sharma').
  If unsure, match with LIKE '%Kohli%'.
"""

genai_client = genai.Client(vertexai=True, project=PROJECT, location=VERTEX_LOCATION)
bq = bigquery.Client(project=PROJECT, location=BQ_LOCATION)


def load_schema():
    lines = []
    for t in bq.list_tables(f"{PROJECT}.{DATASET}"):
        table = bq.get_table(t)
        cols = ", ".join(f"{f.name} {f.field_type}" for f in table.schema)
        lines.append(f"`{PROJECT}.{DATASET}.{t.table_id}` ({table.num_rows} rows): {cols}")
    return "\n".join(lines)


def new_stats():
    return {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "gemini_s": 0.0, "bq_s": 0.0,
            "total_s": 0.0, "gemini_calls": 0, "dry_runs": 0, "queries": 0, "retries": 0,
            "bytes": 0}


def ask_model(prompt, stats):
    start = time.perf_counter()
    resp = genai_client.models.generate_content(model=MODEL, contents=prompt)
    stats["gemini_s"] += time.perf_counter() - start
    stats["gemini_calls"] += 1
    usage = resp.usage_metadata
    if usage:
        # total includes Gemini 2.5 "thinking" tokens, so it can exceed in + out
        stats["tokens_in"] += usage.prompt_token_count or 0
        stats["tokens_out"] += usage.candidates_token_count or 0
        stats["tokens_total"] += usage.total_token_count or 0
    return (resp.text or "").strip()


def extract_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip().rstrip(";")


def is_read_only(sql):
    head = re.sub(r"--.*?$|/\*.*?\*/", "", sql, flags=re.S | re.M).strip().upper()
    return head.startswith(("SELECT", "WITH")) and ";" not in sql


def run_query(sql, stats):
    start = time.perf_counter()
    try:
        stats["dry_runs"] += 1
        dry = bq.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
        if dry.total_bytes_processed > MAX_BYTES:
            raise ValueError(f"query would scan {dry.total_bytes_processed:,} bytes (limit {MAX_BYTES:,})")
        stats["queries"] += 1
        job = bq.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES))
        rows = [dict(r) for r in job.result(max_results=MAX_ROWS)]
        stats["bytes"] += job.total_bytes_processed or 0
        return rows
    finally:
        stats["bq_s"] += time.perf_counter() - start


def split_followups(text):
    parts = re.split(r"^\s*\**FOLLOW-UPS:?\**\s*$", text, maxsplit=1, flags=re.M | re.I)
    if len(parts) < 2:
        return text.strip(), []
    qs = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip() for line in parts[1].splitlines()]
    return parts[0].strip(), [q for q in qs if q][:3]


def format_stats(s, followups=()):
    lines = [
        f"  ⏱  Time: {s['total_s']:.1f}s (Gemini {s['gemini_s']:.1f}s · BigQuery {s['bq_s']:.1f}s)",
        f"  🔢 Tokens: {s['tokens_in']:,} in · {s['tokens_out']:,} out · {s['tokens_total']:,} total",
        f"  🛠  Tools: Gemini ×{s['gemini_calls']} · BigQuery dry-run ×{s['dry_runs']} · "
        f"query ×{s['queries']} · retries {s['retries']} · {s['bytes'] / 1e6:.1f} MB scanned",
    ]
    if followups:
        lines.append("\n  You could also ask:")
        lines += [f"   {i}. {q}" for i, q in enumerate(followups, 1)]
    return "\n".join(lines)


def answer(question, schema, history, stats):
    table_names = ", ".join(re.findall(r"`[^`]+\.([^`.]+)`", schema))
    context = "\n".join(f"Q: {q}\nA: {a}" for q, a in history[-5:])
    base = f"""You write BigQuery Standard SQL for an IPL cricket warehouse.

Tables:
{schema}

Data notes:
{DATA_NOTES}

Recent conversation (for follow-up questions):
{context or '(none)'}

Rules: one read-only SELECT (WITH allowed), fully qualified table names,
LIMIT results to at most {MAX_ROWS} rows, return only the SQL in a ```sql block.

Question: {question}"""

    prompt, error = base, None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            stats["retries"] += 1
        sql = extract_sql(ask_model(prompt, stats))
        try:
            if not is_read_only(sql):
                raise ValueError("only a single SELECT statement is allowed")
            rows = run_query(sql, stats)
            break
        except Exception as e:
            error = str(e)[:500]
            prompt = f"{base}\n\nYour previous SQL:\n{sql}\nfailed with:\n{error}\nFix it."
    else:
        return f"Sorry, I couldn't answer that. Last error: {error}", sql, []

    reply = ask_model(f"""Question: {question}
SQL used:
{sql}
Result rows (JSON, up to {MAX_ROWS}):
{json.dumps(rows, default=str)}

Answer the question concisely and directly from these results only. If the result
is empty or doesn't answer the question, say so. Don't invent numbers.

Then, on its own line, write FOLLOW-UPS: followed by 3 short, related follow-up
questions (one per line) that could be answered from these tables:
{table_names}""", stats)
    summary, followups = split_followups(reply)
    return summary, sql, followups


def main():
    print("Loading schema...")
    schema = load_schema()
    history = []
    print("Ask about IPL data (2008-2026). Type 'exit' to quit, 'sql' to show last query.\n")
    last_sql = None
    session, asked = new_stats(), 0
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in ("exit", "quit"):
            break
        if q.lower() == "sql":
            print(last_sql or "(no query yet)", "\n")
            continue
        stats = new_stats()
        start = time.perf_counter()
        reply, last_sql, followups = answer(q, schema, history, stats)
        stats["total_s"] = time.perf_counter() - start
        history.append((q, reply))
        print(f"\nagent> {reply}\n\n{format_stats(stats, followups)}\n")
        asked += 1
        for k in session:
            session[k] += stats[k]
    if asked:
        print(f"Session total ({asked} question{'s' if asked != 1 else ''}):\n{format_stats(session)}")


if __name__ == "__main__":
    main()
