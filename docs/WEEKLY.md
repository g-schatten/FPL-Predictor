# Weekly plan

Run by the `fpl-weekly` skill (`.claude/skills/fpl-weekly/SKILL.md`) when the user says
"do the weekly update". The skill reads this file, does the routine, works the backlog when a
trigger is met, and appends one log line. Keep this file short: edit items, do not pile them up.

## Routine (every week)

1. `fpl refresh`, then `python .claude/skills/fpl-weekly/check.py`.
2. If the rules line or chips differ from `AGENTS.md` "Live game facts", update that section.
3. `python -m pytest -q`.
4. `fpl wildcard --no-refresh`, and `fpl transfers --name <squad> --no-refresh` for each saved
   squad the user cares about. Report the picks briefly.
5. If code under `src/fpl_predictor/models`, `optimize` or `eval` changed since the last log
   line, run both backtests and check `docs/EVAL.md` still matches.
6. Check the backlog triggers below. Do any item whose trigger is met.
7. Append a log line. Commit only if the user asks.

## Backlog (trigger → action)

| Trigger | Action |
|---|---|
| ≥ 10 finished GWs with a pre-deadline snapshot (`check.py` shows the count) | Build the live scorecard: engine vs form/price/live `ep_next` on 2026-27 GWs, from pre-deadline snapshots only. Add to `docs/EVAL.md` |
| GW19 deadline approaching (first-half chips expire after GW19) | Remind the user to use first-half chips. Report only; no chip planner exists |
| vaastav posts a 2026-27 dump (January window or season end) | Add `2026-27` to `VAASTAV_SEASONS`; re-run the DC item and the GW2–5 team-prior test (`docs/EVAL.md`, "Tested and cut") on it |
| New season (bootstrap season changes, GW1 upcoming) | Re-verify all rules in `AGENTS.md`; clear `data/snapshots/live/` cache of the old season; check `models/scoring.py` against the published points table |
| A transfers-mode change is proposed | Build the transfers gate first (wildcard start at every GW 6–30, `docs/EVAL.md`) |
| `data/snapshots/` over ~2 GB | Keep pre-deadline snapshots and the latest; delete the rest (ask first) |

## Log

One line per week: date · GW · what changed · what was done.

- 2026-10-23 · GW8 pre-deadline · plan created · pre-deadline snapshots GW5/7/8 (1 of 10 finished)
