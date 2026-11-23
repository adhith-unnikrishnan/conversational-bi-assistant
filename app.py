"""Streamlit chat UI:  streamlit run app.py"""
import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))
from cbi.assistant import Assistant  # noqa: E402
from cbi.insights import monthly_pulse  # noqa: E402

st.set_page_config(page_title="Conversational BI Assistant", layout="wide")
bot = st.cache_resource(Assistant)()
st.title("Conversational BI Assistant")
st.caption(f"Engine: {bot.engine} · set ANTHROPIC_API_KEY to use Claude for free-form questions")

with st.sidebar:
    month = st.selectbox("Auto-insights month", [f"2025-{m:02d}" for m in range(12, 0, -1)])
    for line in monthly_pulse(bot.con, month):
        st.write("• " + line)

if q := st.chat_input("e.g. Top 5 products by gross margin in Scotland"):
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        try:
            a = bot.ask(q)
            st.write(a.text)
            df = a.data
            if a.chart == "line":
                st.plotly_chart(px.line(df, x=df.columns[0], y=df.columns[1]), use_container_width=True)
            elif a.chart == "bar":
                st.plotly_chart(px.bar(df, x=df.columns[1], y=df.columns[0], orientation="h"), use_container_width=True)
            st.dataframe(df, use_container_width=True)
            with st.expander("SQL"):
                st.code(a.sql, language="sql")
        except Exception as e:
            st.error(f"Couldn't answer that: {e}")
