from __future__ import annotations

FORBIDDEN_SAME_GW = frozenset(
    {
        "total_points",
        "minutes",
        "starts",
        "goals_scored",
        "assists",
        "defensive_contribution",
        "bonus",
        "bps",
        "yellow_cards",
        "red_cards",
    }
)


def assert_no_leakage(columns: list[str]) -> None:
    leaked = FORBIDDEN_SAME_GW.intersection(columns)
    if leaked:
        raise ValueError(f"Same-GW outcome columns leaked into features: {sorted(leaked)}")
