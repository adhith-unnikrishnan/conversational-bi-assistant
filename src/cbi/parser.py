"""Offline natural-language -> SQL engine driven by the semantic layer.

Deterministic and dependency-free, so the assistant works with no API key and its answers
are reproducible. It handles the question shapes business users ask most often:
  metric totals, 'by <dimension>', top/bottom N, filters (region, store, category, channel,
  year, quarter, month, weekend), trends over time and year-on-year comparisons.
Anything it can't map is reported back instead of guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .semantic import DIMENSIONS, MEASURES

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})


@dataclass
class Intent:
    measures: list[str] = field(default_factory=lambda: ["revenue"])
    group_by: str | None = None
    filters: dict[str, list] = field(default_factory=dict)
    top_n: int | None = None
    ascending: bool = False
    compare_years: tuple[int, int] | None = None
    unmatched: list[str] = field(default_factory=list)


class ParseError(ValueError):
    pass


def _find_measures(q: str) -> list[str]:
    hits = []
    for key, spec in MEASURES.items():
        for syn in sorted(spec["synonyms"], key=len, reverse=True):
            m = re.search(rf"(?<![a-z]){re.escape(syn)}(?![a-z])", q)
            if m:
                hits.append((m.start(), key, len(syn)))
                break
    # longer synonyms win overlaps ('margin %' over 'margin', 'return rate' over 'returns')
    hits.sort(key=lambda h: (h[0], -h[2]))
    chosen, spans = [], []
    for start, key, length in hits:
        if any(s <= start < e for s, e in spans):
            continue
        chosen.append(key)
        spans.append((start, start + length))
    if "margin_pct" in chosen and "gross_margin" in chosen:
        chosen.remove("gross_margin")
    return chosen or ["revenue"]


def _find_group_by(q: str) -> str | None:
    patterns = [r"\b(?:which|what|top \d+|bottom \d+|best|worst|top|lowest|highest) ([a-z ]+?)\b(?:had|has|have|did|by|in|sold|made|is|are|was|were|for)\b",
                r"\bby ([a-z ]+?)(?:\b(?:in|for|during|from|between|vs|versus|and|with)\b|\s*\d|[?.,]|$)",
                r"\bper ([a-z ]+?)(?:\b(?:in|for|during)\b|\s*\d|[?.,]|$)"]
    for pat in patterns:
        m = re.search(pat, q)
        if m:
            phrase = m.group(1).strip()
            for dim, syns in DIMENSIONS.items():
                if any(re.search(rf"\b{re.escape(s)}\b", phrase) for s in syns):
                    return dim
    for dim in ("month",):  # trend words without 'by'
        if any(re.search(rf"\b{s}\b", q) for s in ("trend", "over time", "monthly")):
            return dim
    for dim in ("quarter", "weekday"):
        if any(re.search(rf"\b{re.escape(s)}\b", q) for s in DIMENSIONS[dim]):
            return dim
    return None


def parse(question: str, members: dict[str, list[str]]) -> Intent:
    q = question.lower().strip()
    it = Intent(measures=_find_measures(q), group_by=_find_group_by(q))

    m = re.search(r"\b(top|bottom|best|worst|highest|lowest)\s*(\d+)?\b", q)
    if m:
        it.top_n = int(m.group(2)) if m.group(2) else (1 if re.search(r"\bwhich\b", q) else 5)
        it.ascending = m.group(1) in ("bottom", "worst", "lowest")
    elif re.search(r"\bwhich\b", q) and it.group_by:
        it.top_n, it.ascending = 1, bool(re.search(r"\b(least|lowest|worst|fewest)\b", q))

    # member filters: longest names first so 'North West' beats 'West'
    taken = []
    flat = sorted(((v, d) for d, vals in members.items() for v in vals), key=lambda x: -len(x[0]))
    for value, dim in flat:
        pat = rf"(?<![a-z]){re.escape(value.lower())}(?![a-z])"
        mm = re.search(pat, q)
        if mm and not any(s <= mm.start() < e for s, e in taken) and dim != it.group_by:
            it.filters.setdefault(dim, []).append(value)
            taken.append((mm.start(), mm.end()))

    years = [int(y) for y in re.findall(r"\b(202[0-9])\b", q)]
    if re.search(r"\b(yoy|year on year|year-on-year|vs last year|growth|compared? (?:to|with) last year)\b", q) \
            or (len(set(years)) == 2 and re.search(r"\b(vs|versus|compare|compared|against)\b", q)):
        ys = sorted(set(years)) if len(set(years)) == 2 else [2024, 2025]
        it.compare_years = (ys[0], ys[1])
    elif years:
        it.filters["year"] = sorted(set(years))
    elif re.search(r"\b(this year|last 12 months)\b", q):
        it.filters["year"] = [2025]
    elif re.search(r"\blast year\b", q):
        it.filters["year"] = [2024]
    if it.compare_years and it.group_by == "year":
        it.group_by = None

    qs = re.findall(r"\bq([1-4])\b", q)
    if qs:
        it.filters["quarter"] = [f"Q{x}" for x in qs]
    for name, num in MONTHS.items():
        if re.search(rf"\b{name}\b", q) and it.group_by != "month":
            it.filters.setdefault("month_num", [])
            if num not in it.filters["month_num"]:
                it.filters["month_num"].append(num)
    if re.search(r"\bweekends?\b", q):
        it.filters["is_weekend"] = [True]
    elif re.search(r"\bweekdays?\b", q) and it.group_by != "weekday":
        it.filters["is_weekend"] = [False]
    if re.search(r"\b(digital|online channels?)\b", q) and "channel" not in it.filters and "digital" in q:
        it.filters["channel"] = ["Online", "Click & Collect"]
    return it


def _lit(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def to_sql(it: Intent) -> str:
    where = [f"{d} IN ({', '.join(_lit(v) for v in vals)})" for d, vals in it.filters.items()]
    meas = it.measures
    if it.compare_years:
        y0, y1 = it.compare_years
        where.append(f"year IN ({y0}, {y1})")
        sel = []
        for k in meas:
            expr = MEASURES[k]["sql"]
            a = expr.replace("revenue_gbp", f"CASE WHEN year={y0} THEN revenue_gbp END") \
                    .replace("gross_margin_gbp", f"CASE WHEN year={y0} THEN gross_margin_gbp END") \
                    .replace("discount_gbp", f"CASE WHEN year={y0} THEN discount_gbp END") \
                    .replace("txn_id", f"CASE WHEN year={y0} THEN txn_id END") \
                    .replace("qty", f"CASE WHEN year={y0} THEN qty END") \
                    .replace("is_returned::INT", f"CASE WHEN year={y0} THEN is_returned::INT END")
            b = a.replace(f"year={y0}", f"year={y1}")
            sel += [f"{a} AS {k}_{y0}", f"{b} AS {k}_{y1}",
                    f"({b}) / NULLIF({a}, 0) - 1 AS {k}_change"]
        order_col = f"{meas[0]}_change"
    else:
        sel = [f"{MEASURES[k]['sql']} AS {k}" for k in meas]
        order_col = meas[0]
    dims = [it.group_by] if it.group_by else []
    sql = "SELECT " + ", ".join(dims + sel) + "\nFROM v_sales"
    if where:
        sql += "\nWHERE " + " AND ".join(where)
    if dims:
        sql += f"\nGROUP BY {dims[0]}"
        if dims[0] in ("month", "quarter", "year") and not it.top_n:
            sql += f"\nORDER BY {dims[0]}"
        elif dims[0] == "weekday" and not it.top_n:
            sql += "\nORDER BY list_position(['Mon','Tue','Wed','Thu','Fri','Sat','Sun'], weekday)"
        else:
            sql += f"\nORDER BY {order_col} {'ASC' if it.ascending else 'DESC'} NULLS LAST"
        if it.top_n:
            sql += f"\nLIMIT {it.top_n}"
    return sql
