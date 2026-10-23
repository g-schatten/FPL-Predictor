---
name: fpl-weekly
description: Weekly check-in for the FPL predictor at /home/schatten/Documents/fpl-predictor. Use when the user, in this repo, says "do the weekly update", "weekly update" or "weekly check-in". Refreshes FPL data, verifies live rules, runs tests, reports this week's wildcard/transfer picks, works triggered backlog items in docs/WEEKLY.md, and logs the week.
---

# FPL weekly update

The plan and log live in `docs/WEEKLY.md`. Follow its Routine section in order. Be token-lean:

- Read only `docs/WEEKLY.md` and the tail of `git log --oneline` at the start. Read other files
  only when a step needs them.
- Use `check.py` output instead of reading snapshots. Use `tail`/`grep` on long command output.
- Skip the backtests (step 5) unless model, optimizer or eval code changed since the last log line.
- Activate the venv first: `source .venv/bin/activate`.

Project rules still apply (`CLAUDE.md`): HiGHS picks squads, no `ep_next`/`xP` as features,
any projection change needs `fpl backtest` to beat baselines, do not commit unless asked.

## Report to the user (short)

1. Data: GW, deadline, whether this run is pre-deadline, rule changes if any.
2. Tests: pass/fail count.
3. Picks: captain, transfers (in/out, hits) per squad, wildcard XI xPts. Flag injured starters.
4. Backlog: items triggered and done, or next trigger and how far off.
5. Plan changes made to `docs/WEEKLY.md`.

## Updating the plan

Add a backlog row when a new idea or deferred item appears. Delete a row when done and note it
in the log line. Keep the log to one line per week. If the log passes ~30 lines, collapse old
lines into a one-line summary per season.
