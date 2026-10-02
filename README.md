# ai-agent

A simple Python program that lets you chat with a large language model (LLM) from your terminal.

## Purpose

ai-agent is a thin wrapper around an LLM. It handles the details of sending your messages to the model and showing its replies, so you can have a back-and-forth conversation without writing any API code yourself.

The goals are to:

- Give users an easy way to talk to an LLM through a chat-style interface
- Keep the conversation history so the model remembers what was said earlier in the session
- Stay small and readable, so the code is easy to understand and extend

## Usage

`agent.py` answers questions about the IPL warehouse (BigQuery `ipl-nao.ipl_db`) using
Gemini on Vertex AI. It writes SQL, checks it with a dry run, runs it read-only with a
100 MB scan cap, retries on errors, and explains the result. Type `sql` to see the last query.

```bash
python3 -m venv .venv && .venv/bin/pip install google-genai google-cloud-bigquery
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/workshop-user-key.json   # keep outside this repo
.venv/bin/python agent.py
```
