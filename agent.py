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


def ask_model(prompt):
    return genai_client.models.generate_content(model=MODEL, contents=prompt).text.strip()


def extract_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip().rstrip(";")


def is_read_only(sql):
    head = re.sub(r"--.*?$|/\*.*?\*/", "", sql, flags=re.S | re.M).strip().upper()
    return head.startswith(("SELECT", "WITH")) and ";" not in sql


def run_query(sql):
    dry = bq.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    if dry.total_bytes_processed > MAX_BYTES:
        raise ValueError(f"query would scan {dry.total_bytes_processed:,} bytes (limit {MAX_BYTES:,})")
    job = bq.query(sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES))
    return [dict(r) for r in job.result(max_results=MAX_ROWS)]


def answer(question, schema, history):
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
    for _ in range(MAX_ATTEMPTS):
        sql = extract_sql(ask_model(prompt))
        try:
            if not is_read_only(sql):
                raise ValueError("only a single SELECT statement is allowed")
            rows = run_query(sql)
            break
        except Exception as e:
            error = str(e)[:500]
            prompt = f"{base}\n\nYour previous SQL:\n{sql}\nfailed with:\n{error}\nFix it."
    else:
        return f"Sorry, I couldn't answer that. Last error: {error}", sql

    summary = ask_model(f"""Question: {question}
SQL used:
{sql}
Result rows (JSON, up to {MAX_ROWS}):
{json.dumps(rows, default=str)}

Answer the question concisely and directly from these results only. If the result
is empty or doesn't answer the question, say so. Don't invent numbers.""")
    return summary, sql


def main():
    print("Loading schema...")
    schema = load_schema()
    history = []
    print("Ask about IPL data (2008-2026). Type 'exit' to quit, 'sql' to show last query.\n")
    last_sql = None
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q.lower() in ("exit", "quit"):
            break
        if q.lower() == "sql":
            print(last_sql or "(no query yet)", "\n")
            continue
        reply, last_sql = answer(q, schema, history)
        history.append((q, reply))
        print(f"\nagent> {reply}\n")


if __name__ == "__main__":
    main()
