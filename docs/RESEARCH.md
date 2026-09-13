# FPL Predictor — Research

Researched 2026-09-13. Live FPL API checked the same day.

This project is **not** unique. The honest ones already split the problem into (1) expected-points models and (2) a constraint solver. The ones that ask a single “AI” to spit out a team are weaker and harder to trust.

## 1. Live FPL data — is a complete latest dataset available?

**Yes.** The official public API is complete for the current season and is the right refresh-on-every-run source.

Base: `https://fantasy.premierleague.com/api/`

Verified 2026-09-13:

| Check | Result |
|---|---|
| `GET /bootstrap-static/` | HTTP 200, ~1.7 MB |
| Players | 657 |
| Clubs | 20 |
| Events | 38 |
| `GET /fixtures/` | 380 rows (30 finished, 350 remaining) |
| `GET /element-summary/{id}/` | `history`, `fixtures`, `history_past` |
| Registered managers | ~10.7 million |
| Current event | GW4 (unfinished) |
| Next deadline | GW5, 2026-09-18 17:30 UTC |

`bootstrap-static` already includes: prices, form, status, news, chance of playing, ICT, FPL’s own xG/xA/xGI/xGC, `ep_this` / `ep_next`, set-piece order, defensive contribution, chips, and **live game rules**.

`fixtures` includes home/away, kickoff, FDR (`team_h_difficulty` / `team_a_difficulty`), and finished scores.

`element-summary` is the per-player time series (this season by GW plus previous-season totals).

Caveats:

- There is **no official documentation**. Community maps: [Oliver Looney](https://www.oliverlooney.com/blogs/FPL-APIs-Explained), [mcclowes/fpl-oas](https://github.com/mcclowes/fpl-oas).
- Browser frontends are blocked by CORS. A local Python client is fine.
- `element-summary` is one request per player. Must cache and rate-limit.
- `ep_next` / `ep_this` update on an undocumented cadence. Post-deadline values leak future information. Snapshot them **before** the deadline if they will be used as features.
- Authenticated `/my-team/{manager_id}/` is required for live selling prices, bank, and unused chips. Public `/entry/{id}/event/{gw}/picks/` only shows a published squad.
- `teams[].strength` is currently **null**; attack/defence strength fields are **0**. Only coarse home/away overall ratings remain. Do not use FPL team-strength as a model feature.

### Historical FPL (for training)

[vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League) (~1.8k stars) is still the standard archive (roughly 2016/17 through 2025/26, GW-level CSVs, fixtures, per-player histories).

**It is no longer a weekly live feed.** After 2024/25: three dumps per season (start, end of January window, season end). For 2025/26 they did post a start dump and a final dump (June 2026). This repo must **self-collect weekly snapshots** from the official API going forward.

Known trap: vaastav `xP` is scraped from `ep_this` **after** the GW and can contain post-match information. Shift or drop it.

## 2. Existing projects — what they do, what to reuse, what to improve

### A. Prediction (the “AI”)

| Project | Method | Data | Lesson |
|---|---|---|---|
| [OpenFPL](https://github.com/daniegr/OpenFPL) + [arXiv:2508.09992](https://arxiv.org/abs/2508.09992) | Position-specific RF + XGBoost ensembles (median of ~50 models). Horizons 1–3 GW. | FPL + Understat only. Train 2020/21–2023/24, test 2024/25. | Public data can match FPL Review’s Massive Data Model on high-return players. **Best open baseline to beat.** |
| [SmartPlay Dastan](https://github.com/qazybekb/smartplayfpl-dastan) | Conditional points model; 286 features; weights + negative results published. | 6 seasons, 163k player-fixtures; FPL + Understat; **deadline-anchored** `ep_next`. | Leakage discipline is the whole game. Pre-deadline `ep_next` NDCG@10 ~0.29 vs a leaky scrape ~0.41. Missing projections must be `-1`, not `0`. |
| [daniel-mehta/fpl-forecast](https://github.com/daniel-mehta/fpl-forecast) | Separate minutes model + component xPts + fixture simulation. | Availability timestamps; rolling-origin tests. | Model minutes and events separately. Tag `source_available_time`. |
| [jme-taylor/fantasy_football](https://github.com/jme-taylor/fantasy_football) | 3-class minutes classifier (0 / 1–59 / 60+). | Own warehouse after vaastav weekly died. | Minutes are a first-class model, not a feature you hope XGBoost infers. |
| FPL Review Massive Data | Closed commercial EV + xMins, hourly, bookmaker + news. | Proprietary. CSV export for subscribers. | Use later as an optional uploaded projection file. Never scrape. Not a training label. |

OpenFPL feature idea to copy: rolling means over last 1/3/5/10/38 matches for player, team, and opponent, plus availability; different columns for GKP vs outfield.

Gaps we should close (none of the open stacks do all of these well):

1. Dedicated minutes / rotation model (Europe + cups).
2. Club Elo (FPL strength is broken right now).
3. Multi-year H2H, not just this season’s opponent form.
4. Multi-competition workload (UCL midweek → rotation).
5. Era-aware targets after 2025/26 defensive contribution.
6. Honest walk-forward that must beat `ep_next` on **ranking** metrics, not only MAE.
7. Our own weekly snapshot store so we do not depend on vaastav.

### B. Optimization (the roster / transfer engine)

| Project | Method | Lesson |
|---|---|---|
| [solioanalytics/open-fpl-solver](https://github.com/solioanalytics/open-fpl-solver) (Sertalp) | Deterministic MILP, HiGHS, multi-GW, chips. | **This is the standard.** Projections in, legal plan out. |
| [daniegr/FPL-Optimization-Tools](https://github.com/daniegr/FPL-Optimization-Tools) | Same family: wildcard/regular solves, sensitivity, noise. | Treat projections as noisy; show alternative solutions. |
| [qazybekb/smartplayfpl-solver](https://github.com/qazybekb/smartplayfpl-solver) | HiGHS; sell-on fee; 2026/27 two-half chips; locks/bans. | Optimizer and prediction repo should stay separate. Encode half-profit selling prices. |
| [abdul-gendy/FPL_wildcard_team_selector](https://github.com/abdul-gendy/FPL_wildcard_team_selector) | Heuristic wildcard from FPL + extra stats. | Fine as UX inspiration; weaker than MILP. |
| [owen-lacey/fpl-team-picker](https://github.com/owen-lacey/fpl-team-picker) | Wrapper around a user’s team + xP. | Good product shape: wildcard vs transfers. |
| [om-gupta-30/ML-FPL-Predictor](https://github.com/om-gupta-30/ML-FPL-Predictor) | Full-stack: analyse squad, Monte Carlo, chip tips. | Monte Carlo is useful **after** a points model, not instead of a solver. |
| [Shirazik/fpl-optimizer](https://github.com/Shirazik/fpl-optimizer) | PuLP/HiGHS transfers. | Horizon-weighted objective + hit penalty is the right transfer math. |

Do **not** copy: genetic algorithms, “LLM picks 15 names”, or unconstrained top-by-form lists. Those ignore budget, 3-per-club, selling prices, and hit cost.

### C. What “AI” should mean here

Serious FPL systems are **not** chat models choosing players. They are:

1. Gradient-boosted / ensemble regressors on public match data.
2. A minutes model.
3. A mixed-integer program that respects FPL law.

LLMs are useful later for explaining a solve (“Salah out because minutes + GW5 FDR”), not for searching the squad space.

## 3. Potential datasets

### Tier 1 — required

| Dataset | Refresh | Covers | Role |
|---|---|---|---|
| Official FPL API | Continuous; pull every run | 2026/27 live + this-season history | Prices, availability, FDR, ICT, FPL xG, live rules |
| vaastav FPL archive | 3×/season now | ~2016/17–2025/26 | Historical labels for training |

### Tier 2 — should have (this is how OpenFPL/Dastan get close to paid tools)

| Dataset | Refresh | Covers | Role |
|---|---|---|---|
| Understat (via [soccerdata](https://github.com/probberechts/soccerdata)) | After matches | Top-5 leagues, ~2014/15+ | Player/team xG, xA, PPDA, Deep |
| Club Elo | Daily CSV/API | Long club history | Team strength, home/away, European form |
| football-data.co.uk | Weekly CSVs | PL 1993/94+ plus other divisions | H2H, home/away, odds-as-strength |

### Tier 3 — high value for your stated factors

| Dataset | Refresh | Role |
|---|---|---|
| FBref via soccerdata | Rate-limited scrape | Multi-competition minutes, pressing, squad rotation |
| football-data.org (free key) | Live fixtures/results | Clean lineups, other competitions |
| FPL set-piece notes | Every run | Penalties / corners |

### Tier 4 — optional later

| Dataset | Notes |
|---|---|
| StatsBomb open data | Deep events, incomplete modern PL |
| API-Football | Convenient H2H JSON; tight free quota |
| FPL Review CSV | Paid projections to **compare**, not to train |
| Transfermarkt (worldfootballR / soccerdata) | Injury/market metadata; scrape-fragile |

### Mapping problem

FPL `id` changes every season. FPL `code` is the stable player key. Understat, FBref, and football-data.co.uk all have different IDs. Dastan ships audited FPL↔Understat maps; still expect 50–80 unresolved names on a new season. Unmapped players must degrade to FPL-only features, not be dropped silently.

## 4. 2026/27 rules the solver must encode

From live `bootstrap-static` + Premier League announcements:

- £100.0m, 15 players, ≤3 per club, 2/5/5/3.
- 1 FT/GW, bank up to 5, extras cost −4, cap 20 transfers.
- Sell-on fee 50% of price rises.
- Two chip sets (WC, FH, BB, TC) for GW1–19 and GW20–38. WC/FH from GW2. One chip per GW. First-half chips die after GW19 (deadline 2027-01-02 13:30 GMT).
- Defensive contribution: DEF +2 at 10 CBIT; MID/FWD +2 at 12 CBIRT. BPS tweaked this season to reduce overlap with DC.
- No extra December FTs (AFCON not in 2026/27).

## 5. Recommended stance

Build a **small, testable clone of the OpenFPL + Sertalp stack**, then add the gaps above.

Do not start by training a giant unstructured model. Do not scrape FPL Review. Do not wait on vaastav weekly dumps.

Success metric: on a walk-forward of completed 2026/27 GWs (and held-out 2024/25–2025/26), a solver fed with **our** projections scores more FPL points than the same solver fed with official `ep_next`.
