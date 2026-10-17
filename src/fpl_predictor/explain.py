from __future__ import annotations

from dataclasses import dataclass, field

from fpl_predictor.data.rules import POSITIONS
from fpl_predictor.data.snapshots import Snapshot
from fpl_predictor.optimize.wildcard import WildcardPlan


@dataclass
class TrustNote:
    """Why a recommendation can be trusted, and where it stops being certain."""

    pulled_at: str
    gameweek: int | None
    deadline: str | None
    solver_status: str
    horizon: int
    legality: list[str] = field(default_factory=list)
    risky_starters: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)

    @property
    def span(self) -> str:
        if self.horizon == 1:
            return f"GW{self.gameweek}" if self.gameweek else "the upcoming gameweek"
        return f"the next {self.horizon} gameweeks"

    @property
    def risk_line(self) -> str:
        if not self.risky_starters:
            return "No starter is flagged injured or unavailable in this snapshot."
        return "Starters to double-check before you confirm: " + ", ".join(self.risky_starters) + "."


def build_trust_note(snapshot: Snapshot, plan: WildcardPlan, *, horizon: int) -> TrustNote:
    nxt = snapshot.next_event()
    rules = snapshot.rules
    squad_shape = " / ".join(
        f"{rule.squad_select} {POSITIONS.get(pos_id, rule.short)}"
        for pos_id, rule in sorted(rules.positions.items())
    )
    spent = sum(pick.player.now_cost for pick in plan.picks)
    return TrustNote(
        pulled_at=str(snapshot.meta.get("pulled_at") or "unknown"),
        gameweek=int(nxt["id"]) if nxt else None,
        deadline=str(nxt.get("deadline_time")) if nxt else None,
        solver_status=plan.status,
        horizon=horizon,
        legality=[
            f"Squad cost £{spent / 10:.1f}m of the £{rules.budget / 10:.1f}m budget",
            f"Max {rules.team_limit} players per club",
            f"Squad shape {squad_shape}",
        ],
        risky_starters=[
            pick.player.web_name
            for pick in plan.starters
            if pick.player.availability < 1 or pick.player.risk_flags
        ],
        basis=[
            "each player's xG, xA, bonus and defensive-action rates per 90 minutes",
            "the specific opponent's attack and defence strength, plus home or away",
            "clean-sheet and defensive-contribution odds, not average outcomes",
            "expected minutes from recent selection, injury status and playing chance",
        ],
    )
