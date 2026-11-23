"""Auto-insights: a metric digest in the spirit of Tableau Pulse / Alteryx Auto Insights.

For a metric and two periods it answers 'what changed and why?':
  1. headline change,
  2. driver analysis: which members of each dimension contributed most to the change
     (contribution = member's delta / total delta),
  3. mix shift: segments whose share of the metric moved most,
  4. concentration: how much the top segment accounts for.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DIMS = ["region", "category", "channel", "store_name"]


@dataclass
class Period:
    label: str
    start: str
    end: str  # inclusive


def _by(con, dim: str, p: Period) -> pd.Series:
    return con.execute(f"""SELECT {dim} AS k, SUM(revenue_gbp) v FROM v_sales
                           WHERE date BETWEEN ? AND ? GROUP BY 1""", [p.start, p.end]).df().set_index("k")["v"]


def explain_change(con, cur: Period, prev: Period) -> dict:
    tot_c = con.execute("SELECT SUM(revenue_gbp) FROM v_sales WHERE date BETWEEN ? AND ?", [cur.start, cur.end]).fetchone()[0]
    tot_p = con.execute("SELECT SUM(revenue_gbp) FROM v_sales WHERE date BETWEEN ? AND ?", [prev.start, prev.end]).fetchone()[0]
    delta = tot_c - tot_p
    drivers, mix = {}, {}
    for dim in DIMS:
        c, p = _by(con, dim, cur), _by(con, dim, prev)
        df = pd.DataFrame({"current": c, "previous": p}).fillna(0)
        df["delta"] = df["current"] - df["previous"]
        df["contribution"] = df["delta"] / delta if delta else 0
        df["growth"] = df["current"] / df["previous"].replace(0, pd.NA) - 1
        df["share_shift_pts"] = (df["current"] / tot_c - df["previous"] / tot_p) * 100
        drivers[dim] = df.sort_values("delta", ascending=delta < 0)
        mix[dim] = df["share_shift_pts"].abs().max()
    return {"current": tot_c, "previous": tot_p, "delta": delta, "pct": delta / tot_p,
            "drivers": drivers, "mix": mix, "cur": cur, "prev": prev}


def narrate(res: dict) -> list[str]:
    up = res["delta"] >= 0
    lines = [f"Revenue {res['cur'].label} was £{res['current']:,.0f}, {'up' if up else 'down'} "
             f"{abs(res['pct']):.1%} on {res['prev'].label} (£{res['previous']:,.0f})."]
    for dim in ["region", "category", "channel"]:
        d = res["drivers"][dim]
        top = d.iloc[0]
        lines.append(f"Biggest {dim} driver: {top.name} ({'+' if top.delta >= 0 else '-'}£{abs(top.delta):,.0f}, "
                     f"{top.contribution:.0%} of the change; {top.growth:+.1%}).")
    st = res["drivers"]["store_name"]
    worst = st.sort_values("growth").iloc[0]
    if worst.growth < res["pct"] - 0.1:
        lines.append(f"Watch: {worst.name} lagged the chain at {worst.growth:+.1%} vs {res['pct']:+.1%} overall.")
    dim = max(res["mix"], key=res["mix"].get)
    d = res["drivers"][dim]
    mover = d.loc[d["share_shift_pts"].abs().idxmax()]
    lines.append(f"Largest mix shift: {mover.name} share of revenue moved {mover.share_shift_pts:+.1f} pts ({dim}).")
    return lines


def monthly_pulse(con, month: str) -> list[str]:
    """Digest for a calendar month vs the same month a year earlier, e.g. month='2025-11'."""
    m = pd.Period(month, "M")
    ly = m - 12
    cur = Period(m.strftime("%b %Y"), str(m.start_time.date()), str(m.end_time.date()))
    prev = Period(ly.strftime("%b %Y"), str(ly.start_time.date()), str(ly.end_time.date()))
    return narrate(explain_change(con, cur, prev))
