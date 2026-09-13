from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
POSITION_IDS = {name: idx for idx, name in POSITIONS.items()}


@dataclass(frozen=True)
class PositionRule:
    element_type: int
    short: str
    squad_select: int
    min_play: int
    max_play: int


@dataclass(frozen=True)
class ChipWindow:
    name: str
    start_event: int
    stop_event: int


@dataclass(frozen=True)
class GameRules:
    squad_size: int
    squad_play: int
    team_limit: int
    budget: int
    sell_on_fee: float
    max_extra_free_transfers: int
    hit_cost: int
    transfers_cap: int
    positions: dict[int, PositionRule]
    chips: tuple[ChipWindow, ...] = field(default_factory=tuple)

    @property
    def starting_budget_pounds(self) -> float:
        return self.budget / 10


def parse_rules(bootstrap: dict[str, Any]) -> GameRules:
    settings = bootstrap.get("game_settings") or {}
    positions = {
        row["id"]: PositionRule(
            element_type=row["id"],
            short=row["singular_name_short"],
            squad_select=int(row["squad_select"]),
            min_play=int(row["squad_min_play"]),
            max_play=int(row["squad_max_play"]),
        )
        for row in bootstrap.get("element_types") or []
    }
    chips = tuple(
        ChipWindow(
            name=str(chip["name"]),
            start_event=int(chip["start_event"]),
            stop_event=int(chip["stop_event"]),
        )
        for chip in bootstrap.get("chips") or []
    )
    return GameRules(
        squad_size=int(settings.get("squad_squadsize", 15)),
        squad_play=int(settings.get("squad_squadplay", 11)),
        team_limit=int(settings.get("squad_team_limit", 3)),
        budget=int(settings.get("squad_total_spend", 1000)),
        sell_on_fee=float(settings.get("transfers_sell_on_fee", 0.5)),
        max_extra_free_transfers=int(settings.get("max_extra_free_transfers", 4)),
        hit_cost=4,
        transfers_cap=int(settings.get("transfers_cap", 20)),
        positions=positions,
        chips=chips,
    )


def selling_price(purchase_tenths: int, now_tenths: int, sell_on_fee: float = 0.5) -> int:
    """FPL selling price in 0.1m units. User keeps floor(rise * sell_on_fee)."""
    if now_tenths <= purchase_tenths:
        return now_tenths
    rise = now_tenths - purchase_tenths
    keep = int(rise * sell_on_fee)
    return purchase_tenths + keep


def pounds(tenths: int | float) -> float:
    return float(tenths) / 10


def tenths(pounds_value: float) -> int:
    return int(round(float(pounds_value) * 10))
