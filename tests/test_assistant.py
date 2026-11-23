import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cbi import parser  # noqa: E402
from cbi.assistant import Assistant, UnsafeSQL, guard_sql  # noqa: E402
from cbi.insights import monthly_pulse  # noqa: E402

bot = Assistant(engine="offline")


@pytest.mark.parametrize("q,measure,group,filters", [
    ("Revenue by region in 2025", "revenue", "region", {"year": [2025]}),
    ("Top 5 products by gross margin in Scotland", "gross_margin", "product_name", {"region": ["Scotland"]}),
    ("Margin % by channel in December", "margin_pct", "channel", {"month_num": [12]}),
    ("Which category had the lowest return rate?", "return_rate", "category", {}),
    ("Average order value on weekends in London", "aov", None, {"city": ["London"], "is_weekend": [True]}),
    ("Transactions for Click & Collect in the North West", "transactions", None,
     {"channel": ["Click & Collect"], "region": ["North West"]}),
])
def test_parse(q, measure, group, filters):
    it = parser.parse(q, bot.members)
    assert it.measures[0] == measure and it.group_by == group
    for k, v in filters.items():
        assert it.filters[k] == v


def test_top_n_and_direction():
    it = parser.parse("Bottom 3 stores by revenue growth year on year", bot.members)
    assert it.top_n == 3 and it.ascending and it.compare_years == (2024, 2025) and it.group_by == "store_name"


def test_answers_match_direct_sql():
    a = bot.ask("What was total revenue in 2025?")
    direct = bot.con.execute("SELECT SUM(revenue_gbp) FROM v_sales WHERE year = 2025").fetchone()[0]
    assert abs(a.data.iloc[0, 0] - direct) < 0.01 and a.chart == "kpi"


def test_trend_question_gives_line_chart():
    assert bot.ask("Show the monthly revenue trend for Electronics").chart == "line"


@pytest.mark.parametrize("sql", [
    "DROP TABLE fact_sales",
    "SELECT 1; DELETE FROM v_sales",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM fact_sales",
    "COPY v_sales TO 'x.csv'",
])
def test_guard_blocks_unsafe_sql(sql):
    with pytest.raises(UnsafeSQL):
        guard_sql(sql)


def test_guard_allows_cte_over_view():
    guard_sql("WITH t AS (SELECT region, SUM(revenue_gbp) r FROM v_sales GROUP BY 1) SELECT * FROM t")


def test_pulse_explains_change():
    lines = monthly_pulse(bot.con, "2025-11")
    assert lines[0].startswith("Revenue Nov 2025") and any("driver" in line for line in lines)
