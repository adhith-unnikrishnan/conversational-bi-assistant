"""Render a static demo page (GitHub Pages) from real assistant runs."""
from __future__ import annotations

import html
import sys
from pathlib import Path

import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbi.assistant import Assistant  # noqa: E402
from cbi.insights import monthly_pulse  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "index.html"
QUESTIONS = [
    "What was total revenue in 2025?",
    "Revenue by region in 2025",
    "Show the monthly revenue trend for Electronics",
    "Top 5 products by gross margin in Scotland",
    "Which store had the highest sales in Q4 2025?",
    "Bottom 3 stores by revenue growth year on year",
    "Margin % by channel in December",
    "What is the average order value on weekends in London?",
]
BLUE = "#2E5EAA"


def chart(a, first: bool) -> str:
    df = a.data
    if a.chart == "kpi" or df.shape[1] < 2:
        return ""
    x, ycol = df.columns[0], next(c for c in df.columns[1:] if c.endswith("_change")) \
        if any(c.endswith("_change") for c in df.columns) else df.columns[1]
    if a.chart == "line":
        tr = go.Scatter(x=df[x], y=df[ycol], line=dict(color=BLUE, width=2.4))
    else:
        tr = go.Bar(x=df[ycol], y=df[x].astype(str), orientation="h", marker_color=BLUE)
    fig = go.Figure(tr)
    fig.update_layout(height=260 if a.chart == "line" else 60 + 32 * len(df), margin=dict(l=150, r=20, t=10, b=30),
                      paper_bgcolor="white", plot_bgcolor="white", font=dict(family="Inter, Arial", size=12),
                      yaxis=dict(autorange="reversed") if a.chart == "bar" else {},
                      xaxis=dict(gridcolor="#EEE"))
    if ycol.endswith(("_change", "margin_pct", "return_rate")):
        (fig.update_xaxes if a.chart == "bar" else fig.update_yaxes)(tickformat=".0%")
    return fig.to_html(full_html=False, include_plotlyjs="cdn" if first else False, config={"displayModeBar": False})


def main() -> None:
    bot = Assistant(engine="offline")
    cards, first = [], True
    for q in QUESTIONS:
        a = bot.ask(q)
        c = chart(a, first)
        first = first and not c
        cards.append(f"""<div class="card"><div class="q">🧑‍💼 {html.escape(q)}</div>
<div class="a">💡 {html.escape(a.text)}</div>{c}
<details><summary>Generated SQL</summary><pre>{html.escape(a.sql)}</pre></details></div>""")
    pulse = "".join(f"<li>{html.escape(x)}</li>" for x in monthly_pulse(bot.con, "2025-11"))
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Conversational BI Assistant | Adhith Unnikrishnan</title>
<style>
body{{margin:0;background:#F4F6F8;font-family:Inter,Segoe UI,Arial,sans-serif;color:#1F2933}}
header{{background:#14213D;color:#fff;padding:28px 40px}} header h1{{margin:0 0 6px;font-size:26px}}
header p{{margin:0;color:#C9D3E3;font-size:14px;max-width:900px;line-height:1.5}} header a{{color:#9CC3FF}}
main{{max-width:1100px;margin:0 auto;padding:24px;display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}}
@media(max-width:900px){{main{{grid-template-columns:1fr}}}}
.card,.pulse{{background:#fff;border-radius:10px;padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.pulse{{grid-column:1/-1;border-left:4px solid #E07A2F}} .pulse h2{{margin:0 0 8px;font-size:17px}}
.pulse li{{margin:4px 0;font-size:14px}}
.q{{font-weight:600;margin-bottom:8px}} .a{{background:#EEF3FB;border-radius:8px;padding:10px 12px;font-size:14px;margin-bottom:6px}}
details{{font-size:12px;color:#6B7785}} pre{{background:#1F2933;color:#E6EDF3;padding:10px;border-radius:6px;overflow-x:auto;font-size:12px}}
</style></head><body>
<header><h1>Conversational BI Assistant</h1>
<p>Ask business questions in plain English and get SQL, an answer in words, a recommended chart and
auto-generated insights. Like Power BI Copilot, Tableau Pulse or Alteryx Auto Insights, on an open stack (Python + DuckDB, optional Claude LLM).
Every answer below was produced by the offline engine from the
<a href="https://github.com/adhith-unnikrishnan/bi-data-prep-pipeline">star schema</a> at build time.
Source: <a href="https://github.com/adhith-unnikrishnan/conversational-bi-assistant">GitHub</a></p></header>
<main><div class="pulse"><h2>📈 Auto-insights digest: November 2025 vs November 2024</h2><ul>{pulse}</ul></div>
{''.join(cards)}</main></body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
