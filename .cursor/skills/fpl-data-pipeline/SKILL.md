---
name: fpl-data-pipeline
description: Fetches, snapshots, and joins Fantasy Premier League and football datasets without leakage. Use when working on data refresh, FPL API clients, Understat, FBref, Club Elo, football-data.co.uk, player ID mapping, or when the user mentions datasets, scraping, or refresh-on-run.
---

# FPL data pipeline

## Refresh-on-run

Every command that recommends a squad starts with a refresh, then uses the new snapshot.

Official FPL (no key, CORS blocks browsers, fine from Python):

| Endpoint | Use |
|---|---|
| `/bootstrap-static/` | players, teams, events, chips, rules, `ep_next`, status, ICT, FPL xG |
| `/fixtures/` | 380 fixtures, FDR, home/away, finished scores |
| `/element-summary/{id}/` | per-GW history, upcoming fixtures, prior seasons |
| `/event/{gw}/live/` | current GW live stats |
| `/event-status/` | bonus/league processing flags |
| `/team/set-piece-notes/` | penalty / set-piece order |

Optional public squad import (no login): `/entry/{manager_id}/event/{gw}/picks/` and `/entry/{manager_id}/history/`. Current bank, selling prices, and unused chips need either local JSON or the authenticated `/my-team/{id}/`.

Throttle `element-summary` (600+ calls). Cache for the process; persist under `data/snapshots/YYYYMMDDTHHMMZ/`.

## Source tiers

Use this order. Do not scrape paywalled projection sites.

1. **Must — live FPL API.** Complete current-season dataset. Updated continuously. This is the refresh source.
2. **Must — vaastav historical.** https://github.com/vaastav/Fantasy-Premier-League — seasons ~2016/17–2025/26. Weekly updates **stopped after 2024/25**; only start / January window / season-end dumps after that. Use for training history, not as the live feed. Treat `xP` as leak-prone.
3. **Should — Understat** via `soccerdata` (or Understat JSON). Shot-level xG/xA, PPDA, Deep. Core of OpenFPL/Dastan.
4. **Should — Club Elo** (`http://clubelo.com/API`). Daily club strength. Needed because live FPL `teams.strength` is currently null.
5. **Should — football-data.co.uk** CSVs. Multi-decade PL results + odds for H2H and home/away priors.
6. **Nice — FBref** via `soccerdata`. Multi-competition minutes (UCL, Europe, cups) for rotation/fatigue.
7. **Nice — football-data.org** keyed API. Clean fixtures/results/lineups. Free tier ~10 req/min.
8. **Optional — StatsBomb open data.** Event-level, incomplete PL coverage.
9. **Do not depend on — FPL Review / paid Opta / unofficial SofaScore.** Fine as a later optional CSV upload, never as the default pipeline.

## Joins

Canonical player key = FPL `elements.code` (stable) plus season-local `elements.id`.

Maintain `data/mappings/player_external.csv` with `fpl_code`, `understat_id`, `fbref_id`, `season`. Unmapped players stay in the optimizer with FPL-only features; log the gap. Never silently fuzzy-match names in a training join.

## Snapshot contract

Each snapshot writes:

- `meta.json` — pulled_at UTC, current/next GW, deadline, source versions
- `bootstrap.json`, `fixtures.json`
- `players_history.parquet` (from element-summary or incremental live)
- optional `understat/`, `elo/`, `fbref/`

A feature row for GW N is valid only if `pulled_at < events[N].deadline_time`.

## What not to pull every run

- Full FBref history (weekly or on cache miss).
- Entire vaastav clone (once per machine, then reuse).
- Paid APIs.

## Additional resources

- [docs/RESEARCH.md](../../../docs/RESEARCH.md)
- Leakage tests belong with skill `fpl-modeling-eval`
