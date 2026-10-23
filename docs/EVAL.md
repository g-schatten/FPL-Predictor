# Evaluation

Reproduce everything here with:

```bash
fpl backtest --season 2025-26 --start-gw 6
fpl backtest --season 2024-25 --start-gw 6     # replication season (no defensive contribution)
```

To test a change, save a reference before it and compare after it. `--compare` prints
`after − before` per method and metric, with its standard error and win/tie/loss across gameweeks:

```bash
fpl backtest --season 2025-26 --save data/warehouse/ref_2526.csv
# ... apply the change ...
fpl backtest --season 2025-26 --compare data/warehouse/ref_2526.csv
```

## What is being tested

The projection engine is rebuilt from scratch for every gameweek using **only** completed
gameweeks before it: team attack/defence indices, player per-90 rates, position priors, and
minutes profiles. Nothing from the gameweek being predicted is available, including its
results, lineups, and league-wide rates.

2025-26 is the test season because it is the first full season under the current ruleset
(defensive contribution), so its scoring matches what the tool projects today.

## Headline result

33 walk-forward gameweeks, ~790 player-gameweeks scored per gameweek.

| method | NDCG@10 | NDCG@20 | top-20 capture | MAE | XI+captain pts/GW | with autosubs |
|---|---|---|---|---|---|---|
| **engine (shipped)** | **0.373** | **0.394** | **0.408** | **0.968** | **59.3** | **62.6** |
| legacy heuristic (form × FDR × minutes) | 0.303 | 0.330 | 0.345 | 0.995 | 50.2 | 53.8 |
| last-4-GW points per 90 × minutes | 0.284 | 0.310 | 0.330 | 1.031 | 49.0 | 52.5 |
| price | 0.272 | 0.289 | 0.299 | 48.08 | 37.5 | 38.7 |

2024-25, same walk-forward (replication; that season scored no defensive contribution):

| method | NDCG@10 | NDCG@20 | top-20 capture | MAE | XI+captain pts/GW | with autosubs |
|---|---|---|---|---|---|---|
| **engine (shipped)** | **0.411** | **0.418** | **0.423** | **1.043** | **66.2** | **68.5** |
| legacy heuristic | 0.354 | 0.360 | 0.367 | 1.065 | 54.6 | 56.3 |
| last-4-GW points per 90 × minutes | 0.338 | 0.352 | 0.363 | 1.102 | 53.7 | 55.5 |
| price | 0.333 | 0.348 | 0.366 | 47.31 | 46.0 | 47.4 |

The last two columns are the metric that matches how the tool is used: each gameweek the real
MILP solver builds a legal £100.0m 15-man squad from that method's projections. "XI+captain"
counts what the starting XI and captain **actually scored**. "With autosubs" scores the whole 15
the way FPL does: a starter with 0 minutes is replaced by the first bench player who played,
keeping position minimums, and the vice-captain takes the armband if the captain did not play.
The engine gains ~8.5 points a gameweek over the heuristic it replaced.

Caveats, stated plainly:

- Every method gets to rebuild the squad each week with no transfer cost, so the absolute
  points are optimistic. Only the gap between methods is meaningful.
- Historical data has no injury flags or `chance_of_playing`, so the live engine has
  information in production that it lacked here.
- The engine loses on Spearman (0.725 vs 0.744). Spearman is computed over all ~790 rows,
  most of whom are squad filler, so it mostly measures ordering at the bottom of the pool.
  Squad selection depends on the top of the ranking, which is what NDCG and capture measure.
- Squad-level points are noisy across 33 gameweeks; the ranking metrics are the stable signal.

## Why `ep_next` is not in the table

The trust standard asks for a comparison against official FPL expected points. That is not
possible on historical data: the `xP` column in the public archive is **leaked**.

```
gameweeks with any value        11 of 38
correlation with actual points  0.668
top-200 by xP that played 0 min 1%
```

A genuine pre-deadline projection ranks plenty of players who then do not play, and
correlates with realised points far below 0.67 at player-gameweek level. `fpl backtest`
runs this diagnostic (`official_ep_leakage`) and refuses to score the column as a baseline.
Comparing against live `ep_next` requires accumulating pre-deadline snapshots going forward.

## What the engine actually uses

Per player, per fixture, all from the official API:

- **Attacking**: xG and xA per 90, with each match capped at 1.0 xG and 1.0 xA, shrunk toward
  the position median by 320 pseudo-minutes,
  scaled by how good this specific fixture looks for the team.
- **Team strength**: attack and defence indices from finished results plus aggregated player
  xG (keeper xGC for defence), shrunk toward an FDR-derived prior.
- **Fixture**: expected goals for and against from `league_avg × attack × opponent defence ×
  venue`. Clean sheets are `P(0 conceded)` under Poisson; the goals-conceded penalty is
  `E[floor(conceded / 2)]`, not a point estimate.
- **Minutes**: P(appear) and P(60+) from recency-weighted appearances, times availability
  from `status` and `chance_of_playing_next_round`. Live, the per-match minutes come from
  `/event/{gw}/live/` (one cached request per finished gameweek), so the live tool runs the
  same model this backtest scores.
- **Defensive contribution**: `P(appear) × P(actions ≥ threshold)` under Poisson, where the
  actions are scored on the player's minutes *when he plays*, with the position threshold
  (10 CBIT for defenders, 12 CBIRT otherwise).
- **Bonus / saves / cards**: observed per-90 rates, with saves scaled by fixture danger.

## Parameter sweeps

Every constant below was chosen by walk-forward NDCG@20, not by taste.

**Recency weighting of player rates** — season-long rates beat recent form:

| rate half-life | flat | 12 matches | 8 | 4 |
|---|---|---|---|---|
| NDCG@20 | **0.3876** | 0.3844 | 0.3840 | 0.3790 |

**Blending the player's own recent points per 90 into the projection** — makes it worse:

| points blend | 0.0 | 0.2 | 0.35 | 0.5 |
|---|---|---|---|---|
| NDCG@20 | **0.3790** | 0.3784 | 0.3745 | 0.3700 |

**Team strength: xG weight vs goals** — xG is the better strength signal:

| xG weight | 0.0 (goals only) | 0.35 | 0.65 | 0.85 | 1.0 |
|---|---|---|---|---|---|
| NDCG@20 | 0.3791 | 0.3816 | 0.3876 | **0.3894** | 0.3881 |

**Team strength shrinkage** (`prior_games`): flat between 0 and 8 (0.3853–0.3893) and worse
at 20 (0.3782). Shipped value is 3.0, which is inside the flat region and protects
early-season estimates the backtest cannot exercise (it starts once several gameweeks exist).

**Minutes half-life**: 4 matches (0.3876) beat 2 (0.3849), 8 (0.3834) and 20 (0.3852).
Unlike scoring rates, minutes *should* be recency weighted — selection changes, ability does
not.

## Probability calibration

Predicted probabilities are compared with observed frequencies for players who played 60+
minutes (n=6,371):

| event | predicted | actual |
|---|---|---|
| defensive contribution, DEF | 0.258 | 0.271 |
| defensive contribution, MID | 0.163 | 0.189 |
| defensive contribution, FWD | 0.005 | 0.014 |
| clean sheet | 0.267 | 0.253 |

Slightly conservative on defensive contribution, slightly optimistic on clean sheets. Both
are close enough that the points they generate are not systematically inflated.

## Known gaps

- No Club Elo, no head-to-head history, no European/cup minutes for rotation risk.
- Set-piece and penalty duties are available live (`penalties_order`,
  `corners_and_indirect_freekicks_order`) but are not in the historical archive, so they are
  not yet used — they cannot be validated here.
- The XGBoost model in `models/train.py` is not wired into live projections;
  `load_model_adjustments()` returns an empty dict until a trained model beats this engine
  on these same metrics.
- 2024-25 runs as a replication season, but under its own ruleset: it scored no defensive
  contribution, so it cannot test DC changes. 2026-27 will be the second DC season.
- `fpl backtest` scores wildcard squads only. Transfers-mode settings (free-transfer value,
  hit limit, bench weight in transfers) have no gate and stay unchanged until one exists.

## Changes after the first engine (2026-10-17)

### Ship rule

1. **2025-26 decides.** `--compare` must show `diff > 0` on every gate metric the change can
   move: NDCG@10, NDCG@20, top-20 capture and squad points with autosubs. A solver-only change
   can only move squad points. The engine must stay above the form and price baselines.
2. **2024-25 must not reverse it.** No gate metric worse by more than one standard error.
3. **Tuned constants need neighbours.** The values either side must also pass rule 1.
4. Report `se` and win/tie/loss with every result. Gains here are 1–3 standard errors.
5. **No gate, no ship.** If the backtest cannot measure a change, current behaviour stays.

### Shipped

**Bench weight in the wildcard solver** (`optimize/wildcard.py`). Objective is now
`Σ xpts·(start + captain + w·(squad − start))`, `w` = 0.03 for the bench keeper and 0.1 for
outfield players (open-fpl-solver uses per-slot weights of the same size). Before, the solver
was indifferent between a bench player who never plays and one who starts every week.

| | squad with autosubs, diff ± se | win/tie/loss |
|---|---|---|
| 2025-26, w = 0.1 | +2.58 ± 0.88 | 14/14/5 |
| 2025-26, w = 0.05 / 0.2 | +2.58 / +2.42 | |
| 2024-25, w = 0.1 | +1.55 ± 1.27 | 16/8/9 |

The archive has no injury flags, so every blank starter stays in the backtest pool. Live, news
removes roughly half of those before the solve (GW5 2026-27: blank rate among nailed starters
6.1% overall, 3.5% among unflagged). Re-solving with half of each gameweek's non-players
removed gives −0.06, +0.82, +0.58 over three seeds (mean +0.45); with all removed, −0.12 ± 0.16.
Expect about +0.4 points a gameweek live, not +2.6. Transfers mode is unchanged (no gate).

**Defensive contribution scored on minutes when playing** (`models/engine.py`). The +2 is a
step payout, so applying the threshold to *average* minutes (which include matches the player
misses) understates it. A 7.0-actions-per-90 defender who plays 90 minutes half the time was
scored P(≥10 | λ=3.5) = 0.3%; the right value is 0.5 × P(≥10 | λ=7) = 8.5%.

| 2025-26 | diff ± se | win/tie/loss |
|---|---|---|
| NDCG@10 | +0.0057 ± 0.0036 | 10/20/3 |
| NDCG@20 | +0.0030 ± 0.0026 | 16/7/10 |
| top-20 capture | +0.0006 ± 0.0031 | 8/18/7 |
| squad with autosubs | +0.55 ± 0.51 | 8/22/3 |

MAE rises 0.006 (rotation players carry a fatter tail). 2024-25 is identical (no DC). One
season of evidence; retest when 2026-27 is in the archive. Applying the same change to saves
and goals conceded added nothing on 2025-26 and cost slightly on 2024-25, so it is DC only.

**Live minutes from match history** (`data/snapshots.py`, `data/fpl_api.py`,
`models/minutes.py`). Every snapshot before this had `n_histories: 0`, because histories were
only fetched with `--full` (667 requests). The live tool therefore ran the season-total
fallback, not the decayed per-match model scored here. `fpl refresh` now builds the same
history from `/event/{gw}/live/`. A test checks the live and backtest paths give identical
minutes profiles. Backtest scored with history vs the old live fallback:

| | NDCG@10 | NDCG@20 | top-20 | squad with autosubs | MAE |
|---|---|---|---|---|---|
| 2025-26 | +0.0083 ± 0.0078 | +0.0066 ± 0.0065 | +0.0062 ± 0.0085 | +0.18 ± 1.42 | −0.31 |
| 2024-25 | +0.0047 ± 0.0067 | +0.0175 ± 0.0056 | +0.0233 ± 0.0076 | −0.12 ± 2.08 | −0.28 |

A player registered within the last two finished gameweeks with no minutes keeps the signing
guess (45 minutes when fit and £4.5m+); three or more blank rows while fit now project 0.

**Per-match xG/xA cap** (`models/rates.py` `MATCH_CAP = 1.0`, live via per-gameweek xG from
`/event/{gw}/live/`). A season-long rate let one game dominate: in 2026-27 Bruno Fernandes had
2.02 of his 2.66 xG in GW2 (penalties), then 0.64 in six games, and still ranked 3rd among
midfielders. Each match now adds at most 1.0 xG and 1.0 xA. He drops to 11th.

| cap | 2025-26 NDCG@10 / NDCG@20 / top-20 / squad | 2024-25 NDCG@10 / NDCG@20 / top-20 / squad |
|---|---|---|
| 0.5 | −0.0115 / +0.0015 / +0.0162 / −0.09 | −0.0016 / +0.0005 / −0.0019 / +1.88 |
| 0.75 | −0.0001 / +0.0037 / +0.0100 / +0.15 | +0.0086 / +0.0031 / +0.0012 / +1.58 |
| **1.0** | **+0.0007 / +0.0028 / +0.0057 / +0.18** | **+0.0098 / +0.0043 / +0.0017 / +1.79** |
| 1.5 | +0.0003 / +0.0017 / +0.0034 / +0.64 | +0.0054 / +0.0028 / +0.0008 / +1.42 |

1.0 is the only value positive on every gate metric in both seasons. Its lower neighbour misses
one metric by 0.0001 (noise); the upper neighbour passes. Double gameweeks split the live
per-gameweek xG evenly across fixtures, because the live endpoint does not publish it per match.

### Tested and cut

These come from pilot scripts that call the same `eval/backtest.py` functions (not committed).

- **Cross-season player priors** (Marcel-style: last season's totals from vaastav
  `players_raw.csv` matched on `code`, weight 0.2–1.0, capped at 320 or 900 minutes, per
  component). 10 variants; none beat the engine on both NDCG@10 and NDCG@20. With all
  components, w=0.2 gave NDCG@20 0.3850 and w=0.8 gave 0.3796, against 0.3880. Roles change
  every summer: Salah went from 0.66 xG/90 in 2024-25 to 0.34 over the first nine gameweeks of
  2025-26, and the prior kept pulling him back.
- **Team-strength prior** (last season's indices with promoted teams set to the relegated
  mean, or FDR) and **opponent-adjusted strength** (10-iteration multiplicative fit). No prior
  variant was better on all four gate metrics; live stays on FDR, the backtest on no prior.
  The opponent fit gave NDCG@20 −0.0009 and XI+captain −0.36. Priors help in GW2–5 only;
  retest that window (with Club Elo) when 2026-27 is in the archive.
- **Recent form, retested on the current engine** (2026-10-23, after the user saw a one-haul
  player keep getting picked). Blending recent points per 90 at 0.05 / 0.1 / 0.15 and recency
  weighting rates with half-lives of 38 / 20 / 12 matches. On 2025-26 every variant lost NDCG@10
  (−0.003 to −0.007) and squad points (−0.06 to −1.39); 2024-25 was mixed. The real problem was
  one outlier match, which the per-match cap fixes without discarding the rest of the season.
- **Negative-binomial DC** (dispersion 10/20/40): NDCG@20 0.3908/0.3908/0.3899 vs 0.3911 Poisson.
- **Vice-captain weight in the objective**: the vice is already the second-best starter.
- **Transfers-mode defaults**: an 8-week transfer simulator from four wildcard starts was too
  noisy to gate (one gameweek decided most results). Build a gate with a start at every
  gameweek before changing them.
