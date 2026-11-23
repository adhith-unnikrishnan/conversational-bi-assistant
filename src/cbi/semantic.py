"""Semantic layer: the single place where business terms map to SQL.

Both the offline parser and the LLM engine read from this, so 'revenue' means the same
thing whichever engine answers, the same idea as a Power BI semantic model or Tableau
Pulse metric definitions.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

DATA = Path(__file__).resolve().parents[2] / "data"

MEASURES = {
    "revenue": {"sql": "SUM(revenue_gbp)", "fmt": "gbp",
                "synonyms": ["revenue", "sales", "turnover", "takings"]},
    "gross_margin": {"sql": "SUM(gross_margin_gbp)", "fmt": "gbp",
                     "synonyms": ["gross margin", "margin £", "profit", "gross profit"]},
    "margin_pct": {"sql": "SUM(gross_margin_gbp) / NULLIF(SUM(revenue_gbp), 0)", "fmt": "pct",
                   "synonyms": ["margin %", "margin percent", "margin rate", "margin percentage"]},
    "transactions": {"sql": "COUNT(DISTINCT txn_id)", "fmt": "int",
                     "synonyms": ["transactions", "orders", "baskets"]},
    "units": {"sql": "SUM(qty)", "fmt": "int", "synonyms": ["units", "quantity", "items sold"]},
    "aov": {"sql": "SUM(revenue_gbp) / NULLIF(COUNT(DISTINCT txn_id), 0)", "fmt": "gbp2",
            "synonyms": ["average order value", "aov", "basket size", "average basket"]},
    "return_rate": {"sql": "AVG(is_returned::INT)", "fmt": "pct",
                    "synonyms": ["return rate", "returns rate", "returns"]},
    "discount": {"sql": "SUM(discount_gbp)", "fmt": "gbp", "synonyms": ["discount", "markdown"]},
}

DIMENSIONS = {
    "store_name": ["store", "stores", "shop", "shops", "branch"],
    "city": ["city", "cities"],
    "region": ["region", "regions"],
    "country": ["country", "nation"],
    "category": ["category", "categories", "department"],
    "product_name": ["product", "products", "item", "sku"],
    "channel": ["channel", "channels"],
    "month": ["month", "monthly", "by month", "over time", "trend"],
    "quarter": ["quarter", "quarterly"],
    "weekday": ["weekday", "day of week", "day of the week"],
    "year": ["year", "yearly", "annual"],
}

VIEW_SQL = """
CREATE OR REPLACE VIEW v_sales AS
SELECT d.date, d.year, d.quarter, d.month AS month_num, date_trunc('month', d.date) AS month,
       d.weekday, d.is_weekend, d.fiscal_year,
       s.store_id, s.store_name, s.city, s.region, s.country, s.catchment_type,
       p.sku, p.product_name, p.category, c.channel,
       f.txn_id, f.customer_id, f.qty, f.revenue_gbp, f.gross_margin_gbp, f.discount_gbp, f.is_returned
FROM fact_sales f JOIN dim_date d USING (date_key) JOIN dim_store s USING (store_id)
JOIN dim_product p USING (sku) JOIN dim_channel c USING (channel_key)
"""


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for t in ["fact_sales", "dim_date", "dim_store", "dim_product", "dim_channel"]:
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{(DATA / t).as_posix()}.parquet')")
    con.execute(VIEW_SQL)
    return con


def dimension_values(con) -> dict[str, list[str]]:
    """Distinct members of filterable dimensions, used to spot filters like 'in Scotland'."""
    out = {}
    for dim in ["store_name", "city", "region", "country", "category", "product_name", "channel"]:
        out[dim] = [r[0] for r in con.execute(f"SELECT DISTINCT {dim} FROM v_sales").fetchall()]
    return out


def schema_prompt() -> str:
    """Compact schema + metric definitions handed to the LLM."""
    m = "\n".join(f"- {k}: {v['sql']}  (aka {', '.join(v['synonyms'])})" for k, v in MEASURES.items())
    return (
        "You write DuckDB SQL against ONE view, v_sales, with columns:\n"
        "date DATE, year INT, quarter VARCHAR ('Q1'..'Q4'), month_num INT, month DATE (first of month), "
        "weekday VARCHAR ('Mon'..'Sun'), is_weekend BOOL, fiscal_year VARCHAR ('FY25'), store_id, store_name, city, "
        "region, country, catchment_type, sku, product_name, category, channel ('In-store','Online','Click & Collect'), "
        "txn_id, customer_id, qty INT, revenue_gbp DOUBLE, gross_margin_gbp DOUBLE, discount_gbp DOUBLE, "
        "is_returned BOOL.\nData covers 2024-01-01 to 2025-12-30.\n"
        f"Use these metric definitions exactly:\n{m}\n"
    )
