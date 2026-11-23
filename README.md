# Conversational BI Assistant: plain-English questions → SQL, answers, charts and auto-insights

**Live demo → https://adhith-unnikrishnan.github.io/conversational-bi-assistant/**

An "AI for BI" assistant in the spirit of **Power BI Copilot, Tableau Pulse and Alteryx Auto Insights**,
built on an open stack. Business users ask a question in plain English; the assistant:

1. maps it to the **semantic layer** (governed metric definitions such as revenue, margin %, AOV and return rate),
2. generates **SQL** over the retail star schema (DuckDB),
3. runs it through a **read-only SQL guard**,
4. returns an **answer in words**, the data, and a **recommended chart** (KPI, bar or line),
5. and produces a **Pulse-style auto-insights digest** that explains *why* a metric moved (driver
   contributions by region, category and channel, lagging stores, mix shift).

```
"Top 5 products by gross margin in Scotland"
  → SELECT product_name, SUM(gross_margin_gbp) AS gross_margin FROM v_sales
    WHERE region IN ('Scotland') GROUP BY product_name ORDER BY gross_margin DESC LIMIT 5
  → "Top: Smart Speaker with £27,816 gross margin in Scotland."   [bar chart]
```

## Two engines, one semantic layer
| Engine | When | How |
|---|---|---|
| **Offline** (default) | no API key; demos, CI | deterministic parser: metrics, `by <dimension>`, top/bottom N, filters (region, store, city, category, channel, year, quarter, month, weekend) and year-on-year comparisons |
| **LLM** | `ANTHROPIC_API_KEY` set | Claude writes DuckDB SQL from the schema and the same metric definitions (`CBI_MODEL` picks the model) |

Both engines go through `guard_sql`, which allows a single `SELECT`/`WITH` over the `v_sales` view only and
blocks DDL/DML, multiple statements and file-reading table functions. This matters when an LLM writes queries
against business data.

## Auto-insights example (Nov 2025 vs Nov 2024)
- Revenue Nov 2025 was £219,374, up 3.9% on Nov 2024.
- Biggest category driver: Electronics (+£4,824, 58% of the change).
- Watch: Cabot Circus lagged the chain at −14.9% vs +3.9% overall.
- Largest mix shift: Clothing share of revenue moved −1.7 pts.

## Run it
```bash
pip install -r requirements.txt
cd src && python -m cbi "Revenue by region in 2025"     # one-shot
python -m cbi --pulse 2025-11                            # auto-insights digest
python -m cbi                                            # chat in the terminal
cd .. && streamlit run app.py                            # chat UI with charts
python -m pytest -q                                      # 16 tests: parsing, answers vs direct SQL, SQL guard
python src/build_demo.py                                 # rebuilds docs/index.html (GitHub Pages)
```

## Part of a three-project analytics portfolio
1. [BI Data Prep Pipeline](https://github.com/adhith-unnikrishnan/bi-data-prep-pipeline): blend, cleanse, enrich and model
2. [Retail Insights Dashboard](https://github.com/adhith-unnikrishnan/retail-insights-dashboard): visual, predictive and spatial analysis
3. **Conversational BI Assistant** (this repo): AI for BI

**Author:** Adhith Unnikrishnan, MSc Artificial Intelligence (Brunel University London). All data is synthetic.
