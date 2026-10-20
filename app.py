"""Streamlit web interface.  Start with:  streamlit run app.py"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from sql_agent import SQLAgent
from sql_agent.charts import build_chart

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "autos.db"
load_dotenv(ROOT / ".env")

EXAMPLES = [
    "Welche drei Marken hatten 2025 die meisten Neuzulassungen?",
    "Wie hat sich der Anteil von Elektroautos von 2023 bis 2025 entwickelt?",
    "In welchem Bundesland ist BMW am stärksten?",
    "Vergleiche die monatlichen Zulassungen von BYD und Tesla im Jahr 2025.",
]

st.set_page_config(page_title="SQL Analyst Agent", page_icon="📊", layout="wide")
st.title("📊 SQL Analyst Agent")
st.caption(
    "Fragen in natürlicher Sprache → der Agent erkundet das Schema, schreibt SQL, "
    "korrigiert Fehler selbst und fasst das Ergebnis zusammen. "
    "**Hinweis:** Die Zulassungszahlen sind synthetische Demo-Daten."
)

if not os.getenv("ANTHROPIC_API_KEY"):
    st.error("ANTHROPIC_API_KEY fehlt. Lege eine Datei `.env` an (siehe `.env.example`).")
    st.stop()

with st.sidebar:
    st.subheader("Beispielfragen")
    for ex in EXAMPLES:
        if st.button(ex, width="stretch"):
            st.session_state["question"] = ex
    st.divider()
    st.markdown(
        "**Sicherheitsregeln (Guardrails)**\n"
        "- nur `SELECT` / `WITH`\n- genau eine Anweisung\n"
        "- Datenbank read-only geöffnet\n- max. 200 Zeilen, 5 s Timeout"
    )

question = st.text_input("Deine Frage", key="question",
                         placeholder="z. B. Wie viele BMW wurden 2024 in Bayern zugelassen?")

if st.button("Analysieren", type="primary") and question:
    agent = SQLAgent(DB_PATH)
    trace = st.container()

    def show_step(step):
        icon = "⚠️" if step.is_error else "🔧"
        with trace.expander(f"{icon} {step.tool}", expanded=step.is_error):
            if step.tool == "run_sql":
                st.code(step.input.get("query", ""), language="sql")
            elif step.input:
                st.json(step.input)
            st.text(step.output[:3000])

    with st.spinner("Agent arbeitet ..."):
        result = agent.run(question, on_step=show_step)

    st.subheader("Antwort")
    st.write(result.answer)

    cols = st.columns(3)
    cols[0].metric("Werkzeugaufrufe", len(result.steps))
    cols[1].metric("Selbst korrigierte SQL-Fehler", result.sql_errors)
    cols[2].metric("Tokens", f"{result.input_tokens + result.output_tokens:,}".replace(",", "."))
    st.caption(f"Modell: {agent.model}")

    if result.final_result and result.final_result.rows:
        df = pd.DataFrame(result.final_result.rows, columns=result.final_result.columns)
        st.subheader("Daten der letzten Abfrage")
        st.dataframe(df, width="stretch")
        chart = build_chart(df)
        if chart is not None:
            st.altair_chart(chart, width="stretch")
        with st.expander("Finale SQL-Abfrage"):
            st.code(result.final_sql, language="sql")
