"""CLI:  python -m cbi            -> interactive chat
        python -m cbi "question" -> one-shot answer
        python -m cbi --pulse 2025-11 -> auto-insights digest for a month vs last year"""
from __future__ import annotations

import sys

from .assistant import Assistant
from .insights import monthly_pulse


def show(a) -> None:
    print(f"\n[{a.engine}] {a.text}\n\nSQL:\n{a.sql}\n")
    print(a.data.head(15).to_string(index=False))
    print(f"\nSuggested chart: {a.chart}\n")


def main(argv: list[str]) -> None:
    bot = Assistant()
    if argv[:1] == ["--pulse"]:
        for line in monthly_pulse(bot.con, argv[1] if len(argv) > 1 else "2025-11"):
            print("•", line)
        return
    if argv:
        show(bot.ask(" ".join(argv)))
        return
    print("Ask about the retail data (blank line to quit).")
    while (q := input("> ").strip()):
        try:
            show(bot.ask(q))
        except Exception as e:  # keep the chat alive on a bad question
            print(f"Sorry, I couldn't answer that: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
