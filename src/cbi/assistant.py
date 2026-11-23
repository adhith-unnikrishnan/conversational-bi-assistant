"""The assistant: question -> SQL (LLM or offline) -> guarded execution -> answer, chart, insight."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pandas as pd

from . import parser
from .semantic import MEASURES, connect, dimension_values, schema_prompt

FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|pragma|install|load|"
                       r"export|import|call|set|read_csv\w*|read_parquet|read_json\w*|glob|httpfs)\b", re.I)


class UnsafeSQL(ValueError):
    pass


def guard_sql(sql: str, max_rows: int = 500) -> str:
    """Only a single read-only SELECT over v_sales is allowed through to the database."""
    s = sql.strip().rstrip(";").strip()
    s = re.sub(r"^```(?:sql)?|```$", "", s, flags=re.I).strip()
    if ";" in s:
        raise UnsafeSQL("multiple statements are not allowed")
    if not re.match(r"^(select|with)\b", s, re.I):
        raise UnsafeSQL("only SELECT queries are allowed")
    if FORBIDDEN.search(s):
        raise UnsafeSQL("query uses a forbidden keyword or table function")
    tables = set(t.lower() for t in re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", s, re.I))
    ctes = set(t.lower() for t in re.findall(r"\b([a-z_][a-z0-9_]*)\s+as\s*\(", s, re.I))
    if not tables - ctes <= {"v_sales"}:
        raise UnsafeSQL(f"only v_sales may be queried (got {sorted(tables - ctes)})")
    return f"SELECT * FROM ({s}) AS q LIMIT {max_rows}"


def llm_sql(question: str) -> str:
    """Ask Claude for SQL. Needs ANTHROPIC_API_KEY; the model is set with CBI_MODEL."""
    import anthropic  # optional dependency

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.environ.get("CBI_MODEL", "claude-sonnet-5-5"), max_tokens=600,
        system=schema_prompt() + "Return only one DuckDB SELECT statement, no commentary.",
        messages=[{"role": "user", "content": question}])
    return msg.content[0].text


def fmt(v, kind: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    return {"gbp": f"£{v:,.0f}", "gbp2": f"£{v:,.2f}", "pct": f"{v:.1%}", "int": f"{v:,.0f}"}.get(kind, f"{v:,.2f}")


LABEL = {"revenue": "revenue", "gross_margin": "gross margin", "margin_pct": "margin %",
         "transactions": "transactions", "units": "units", "aov": "average order value",
         "return_rate": "return rate", "discount": "discount"}
PLURAL = {"store_name": "stores", "product_name": "products", "category": "categories", "city": "cities",
          "country": "countries", "region": "regions", "channel": "channels"}


@dataclass
class Answer:
    question: str
    sql: str
    data: pd.DataFrame
    text: str
    chart: str  # 'kpi' | 'bar' | 'line' | 'table'
    engine: str


class Assistant:
    def __init__(self, engine: str | None = None):
        self.con = connect()
        self.members = dimension_values(self.con)
        self.engine = engine or ("llm" if os.environ.get("ANTHROPIC_API_KEY") else "offline")

    def ask(self, question: str) -> Answer:
        intent = None
        if self.engine == "llm":
            sql = llm_sql(question)
        else:
            intent = parser.parse(question, self.members)
            sql = parser.to_sql(intent)
        df = self.con.execute(guard_sql(sql)).df()
        return Answer(question, sql.strip(), df, self._narrate(df, intent), self._chart(df), self.engine)

    # ---- presentation ----
    @staticmethod
    def _chart(df: pd.DataFrame) -> str:
        if len(df) == 1 and df.shape[1] <= 3:
            return "kpi"
        first = df.columns[0]
        if first in ("month", "date", "quarter", "year", "weekday"):
            return "line" if first in ("month", "date") else "bar"
        return "bar" if len(df) <= 25 else "table"

    def _narrate(self, df: pd.DataFrame, it: parser.Intent | None) -> str:
        if df.empty:
            return "No rows match that question."
        if it is None:
            return f"Returned {len(df)} row(s)."
        m = it.measures[0]
        kind = MEASURES[m]["fmt"]
        scope = self._scope(it)
        if it.compare_years:
            y0, y1 = it.compare_years
            if it.group_by:
                top = df.iloc[0]
                word = "Weakest" if it.ascending else "Strongest"
                return (f"{word} {LABEL[m]} growth {y0}→{y1}{scope}: {top[it.group_by]} "
                        f"({top[f'{m}_change']:+.1%}); {len(df)} {PLURAL.get(it.group_by, it.group_by)} shown.")
            r = df.iloc[0]
            return (f"{LABEL[m][0].upper() + LABEL[m][1:]}{scope} was {fmt(r[f'{m}_{y1}'], kind)} in {y1} vs "
                    f"{fmt(r[f'{m}_{y0}'], kind)} in {y0} ({r[f'{m}_change']:+.1%}).")
        if not it.group_by:
            parts = [f"{LABEL[k]} {fmt(df.iloc[0][k], MEASURES[k]['fmt'])}" for k in it.measures]
            return (scope.strip()[:1].upper() + scope.strip()[1:] + ": " if scope else "") + ", ".join(parts) + "."
        g = it.group_by
        if g in ("month", "quarter", "year", "weekday") and not it.top_n:
            hi, lo = df.loc[df[m].idxmax()], df.loc[df[m].idxmin()]
            lab = (lambda x: x.strftime("%b %Y")) if g == "month" else str
            return (f"{LABEL[m][0].upper() + LABEL[m][1:]} by {g}{scope}: highest in {lab(hi[g])} "
                    f"({fmt(hi[m], kind)}), lowest in {lab(lo[g])} ({fmt(lo[m], kind)}).")
        top = df.iloc[0]
        lead = "Lowest" if it.ascending else "Top"
        txt = f"{lead}: {top[g]} with {fmt(top[m], kind)} {LABEL[m]}{scope}."
        if kind in ("gbp", "int") and not it.top_n:
            share = top[m] / df[m].sum()
            txt += f" That is {share:.0%} of the total across {len(df)} {PLURAL.get(g, g)}."
        return txt

    @staticmethod
    def _scope(it: parser.Intent) -> str:
        bits = []
        for d, vals in it.filters.items():
            if d == "is_weekend":
                bits.append("weekends" if vals[0] else "weekdays")
            elif d == "month_num":
                bits.append("/".join(pd.Timestamp(2024, v, 1).strftime("%B") for v in vals))
            else:
                bits.append("/".join(str(v) for v in vals))
        return (" in " + ", ".join(bits)) if bits else ""
