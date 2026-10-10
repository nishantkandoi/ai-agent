# ai-agent

A terminal chat agent that answers plain-English questions about IPL cricket data (2008–2026).

## Purpose

You ask a question like "Who took the most wickets in 2023?" and the agent works out the
answer from the IPL warehouse in BigQuery (`ipl-nao.ipl_db`), using Gemini on Vertex AI.
You don't need to write any SQL.

The goals are to:

- Let anyone query IPL data in plain English through a chat-style interface
- Remember the last few questions, so follow-ups like "what about 2022?" work
- Stay safe (read-only queries, capped data scanned) and small enough to read and extend

## How it works

For each question, `agent.py`:

1. Sends Gemini your question, the table schemas (loaded once at startup), notes on data
   quirks, and your last 5 questions with their answers.
2. Gets back a single SQL `SELECT` query.
3. Checks the query is read-only, then does a dry run to make sure it would scan less
   than 100 MB.
4. Runs it and keeps up to 200 result rows.
5. If any step fails, sends the error back to Gemini to fix the query (up to 3 attempts).
6. Asks Gemini to answer your question using only those rows, and to suggest 3 follow-up questions.

Under each answer it prints the time taken, Gemini token usage, and the calls it made
(Gemini, BigQuery dry runs and queries, retries, data scanned). When you quit, it prints
the totals for the session.

## Usage

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/workshop-user-key.json   # keep outside this repo
.venv/bin/python agent.py
```

At the `you>` prompt, type a question. Type `sql` to see the last query, or `exit` to quit.

### Web app

`app.py` is a Streamlit chat UI on top of the same agent. It shows the stats as tiles,
the SQL in an expandable section, and the follow-up questions as clickable buttons.

```bash
.venv/bin/streamlit run app.py   # then open http://localhost:8501
```

### Deploying to Streamlit Community Cloud

1. At [share.streamlit.io](https://share.streamlit.io), sign in with GitHub and create an app
   from this repo (branch `main`, main file `app.py`).
2. Under **Advanced settings → Secrets**, paste the following, copying each field from the
   service-account key JSON:

   ```toml
   app_password = "choose-a-password"

   [gcp_service_account]
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "..."
   client_id = "..."
   token_uri = "https://oauth2.googleapis.com/token"
   ```

The app refuses to start without `app_password` when the key comes from Secrets. Every
question runs on the Google Cloud project's billing, so only share the password with
people you trust.
