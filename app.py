"""
Streamlit web UI for the IPL agent. Reuses the logic in agent.py.

Run:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/workshop-user-key.json
    .venv/bin/streamlit run app.py
"""

import time

import streamlit as st

import agent

st.set_page_config(page_title="IPL Agent", page_icon="🏏")


@st.cache_resource(show_spinner="Loading schema...")
def get_schema():
    return agent.load_schema()


def show_stats(s):
    c1, c2, c3 = st.columns(3)
    c1.metric("Time", f"{s['total_s']:.1f}s",
              help=f"Gemini {s['gemini_s']:.1f}s · BigQuery {s['bq_s']:.1f}s")
    c2.metric("Tokens", f"{s['tokens_total']:,}",
              help=f"{s['tokens_in']:,} in · {s['tokens_out']:,} out (total includes thinking)")
    c3.metric("Scanned", f"{s['bytes'] / 1e6:.1f} MB")
    st.caption(f"🛠 Gemini ×{s['gemini_calls']} · BigQuery dry-run ×{s['dry_runs']} · "
               f"query ×{s['queries']} · retries {s['retries']}")


state = st.session_state
state.setdefault("turns", [])  # dicts: question, reply, sql, followups, stats
state.setdefault("pending", None)

st.title("🏏 IPL Agent")
st.caption("Ask about IPL data (2008–2026) in plain English.")

schema = get_schema()

for i, t in enumerate(state.turns):
    with st.chat_message("user"):
        st.write(t["question"])
    with st.chat_message("assistant"):
        st.write(t["reply"])
        show_stats(t["stats"])
        with st.expander("SQL used"):
            st.code(t["sql"] or "(none)", language="sql")
        if i == len(state.turns) - 1 and t["followups"]:
            st.write("**You could also ask:**")
            for j, q in enumerate(t["followups"]):
                if st.button(q, key=f"fu-{i}-{j}"):
                    state.pending = q
                    st.rerun()

question = st.chat_input("Ask a question") or state.pending
if question:
    state.pending = None
    history = [(t["question"], t["reply"]) for t in state.turns]
    stats = agent.new_stats()
    with st.spinner("Thinking..."):
        start = time.perf_counter()
        reply, sql, followups = agent.answer(question, schema, history, stats)
        stats["total_s"] = time.perf_counter() - start
    state.turns.append({"question": question, "reply": reply, "sql": sql,
                        "followups": followups, "stats": stats})
    st.rerun()

with st.sidebar:
    st.header("Session totals")
    if state.turns:
        total = agent.new_stats()
        for t in state.turns:
            for k in total:
                total[k] += t["stats"][k]
        st.write(f"{len(state.turns)} question(s)")
        show_stats(total)
    else:
        st.write("No questions yet.")
    if st.button("Clear chat"):
        state.turns = []
        st.rerun()
