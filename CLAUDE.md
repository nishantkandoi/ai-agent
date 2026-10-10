# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A natural-language question-answering agent over the IPL cricket warehouse in BigQuery
(`ipl-nao.ipl_db`, location `asia-south1`), using Gemini (`gemini-2.5-flash`) on Vertex AI
(`us-central1`). There are two front ends over one core: a terminal chat (`agent.py`) and a
Streamlit web UI (`app.py`).

## Commands

```bash
.venv/bin/pip install google-genai google-cloud-bigquery streamlit   # deps (no requirements.txt)
export GOOGLE_APPLICATION_CREDENTIALS=/Users/nishant/credentials/workshop_oct2/.local/workshop-user-key.json
.venv/bin/python agent.py          # terminal chat ('sql' = last query, 'exit' = quit)
.venv/bin/streamlit run app.py     # web UI at http://localhost:8501
.venv/bin/python -m py_compile agent.py app.py   # quick syntax check
```

There are no tests, linter or build step. The venv is Python 3.9, so avoid syntax that is
newer than 3.9, such as `match` or `X | Y` type unions.

## Architecture

- `agent.py` holds all of the logic. `app.py` only imports it and renders the results, so
  any behaviour change belongs in `agent.py` and applies to both front ends. Restart
  Streamlit after editing `agent.py`.
- `agent.py` creates both clients at import time (`genai_client`, `bq`), so importing it
  needs credentials.
- Steps for each question, in `answer(question, schema, history, stats)`:
  1. A prompt containing the schema text (from `load_schema()`, cached once per session),
     the hand-written `DATA_NOTES`, the last 5 Q/A pairs, and the rules goes to Gemini,
     which returns SQL.
  2. `extract_sql` then `is_read_only` (must be a single SELECT/WITH).
  3. `run_query`: a dry run that rejects anything over `MAX_BYTES` (100 MB), then a real
     run with `maximum_bytes_billed`, keeping up to `MAX_ROWS` rows.
  4. On any error, the error goes back to Gemini to fix the SQL, up to `MAX_ATTEMPTS` (3).
  5. A second Gemini call answers using only the rows and appends a `FOLLOW-UPS:` line
     with 3 questions, which `split_followups` parses out.
- `answer` returns `(reply, sql, followups)` and fills in a `stats` dict from
  `new_stats()` with tokens, Gemini/BigQuery time, call counts, retries and bytes. The
  caller sets `total_s`. `format_stats` renders it for the terminal, and `app.py` renders
  its own tiles. Session totals are the key-by-key sum of each question's stats.
- Tunables are the constants at the top of `agent.py`.

## Data quirks

`DATA_NOTES` in `agent.py` is the source of truth for things the schema can't show:
match dates stored as epoch nanoseconds, irregular `season` strings ('2007/08' = 2008),
preferring `match_info_v2`, scorecard-style player names, and normalised team names. When
answers come out wrong, fixing them here is usually better than rewriting the code.

## Working with this user

- Do only what's asked. Don't install tools, upgrade Python or scaffold extra files unless
  asked. Propose extras and wait for a go-ahead.
- For non-trivial changes, restate your understanding and ask clarifying questions before
  building.
- Explain things in plain, simple language. The user is still learning how the agent works.
- Commit and push only when asked. Keep README.md in sync with behaviour changes.
- The key file stays outside the repo, and `.gitignore` already excludes `*.json`, `.env`
  and `.secrets/`.
