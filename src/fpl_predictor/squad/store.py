from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fpl_predictor.data.fpl_api import FplClient
from fpl_predictor.data.rules import selling_price, tenths
from fpl_predictor.data.snapshots import Snapshot
from fpl_predictor.paths import squads_dir


@dataclass
class UserSquad:
    name: str
    player_ids: list[int]
    purchase_prices: dict[int, int]
    selling_prices: dict[int, int]
    bank: float
    free_transfers: int
    chips: list[str] = field(default_factory=list)
    locks: list[int] = field(default_factory=list)
    bans: list[int] = field(default_factory=list)
    entry_id: int | None = None
    saved_at: str = ""

    @property
    def bank_tenths(self) -> int:
        return tenths(self.bank)

    def validate(self) -> None:
        if len(self.player_ids) != 15:
            raise ValueError(f"Squad must have 15 players, got {len(self.player_ids)}.")
        if len(set(self.player_ids)) != 15:
            raise ValueError("Squad contains duplicate player ids.")


def _path(name: str) -> Path:
    return squads_dir() / f"{name}.json"


def _keys_to_int(mapping: dict) -> dict[int, int]:
    return {int(k): int(v) for k, v in mapping.items()}


def save_squad(squad: UserSquad) -> Path:
    squad.validate()
    squad.saved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = asdict(squad)
    payload["purchase_prices"] = {str(k): v for k, v in squad.purchase_prices.items()}
    payload["selling_prices"] = {str(k): v for k, v in squad.selling_prices.items()}
    dest = _path(squad.name)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def load_squad(name: str) -> UserSquad:
    dest = _path(name)
    if not dest.exists():
        raise FileNotFoundError(f"No saved squad named '{name}'. Use `fpl squad save`.")
    raw = json.loads(dest.read_text(encoding="utf-8"))
    squad = UserSquad(
        name=raw["name"],
        player_ids=[int(x) for x in raw["player_ids"]],
        purchase_prices=_keys_to_int(raw.get("purchase_prices") or {}),
        selling_prices=_keys_to_int(raw.get("selling_prices") or {}),
        bank=float(raw.get("bank") or 0),
        free_transfers=int(raw.get("free_transfers") or 1),
        chips=list(raw.get("chips") or []),
        locks=[int(x) for x in raw.get("locks") or []],
        bans=[int(x) for x in raw.get("bans") or []],
        entry_id=raw.get("entry_id"),
        saved_at=str(raw.get("saved_at") or ""),
    )
    squad.validate()
    return squad


def list_squads() -> list[str]:
    return sorted(p.stem for p in squads_dir().glob("*.json"))


def squad_from_ids(
    *,
    name: str,
    player_ids: list[int],
    snapshot: Snapshot,
    bank: float,
    free_transfers: int,
    purchase_prices: dict[int, int] | None = None,
    chips: list[str] | None = None,
    entry_id: int | None = None,
) -> UserSquad:
    by_id = {int(p["id"]): p for p in snapshot.players()}
    missing = [pid for pid in player_ids if pid not in by_id]
    if missing:
        raise ValueError(f"Unknown player ids in this snapshot: {missing}")
    purchase = purchase_prices or {pid: int(by_id[pid]["now_cost"]) for pid in player_ids}
    sells = {
        pid: selling_price(purchase.get(pid, int(by_id[pid]["now_cost"])), int(by_id[pid]["now_cost"]), snapshot.rules.sell_on_fee)
        for pid in player_ids
    }
    return UserSquad(
        name=name,
        player_ids=player_ids,
        purchase_prices=purchase,
        selling_prices=sells,
        bank=bank,
        free_transfers=free_transfers,
        chips=chips or [],
        entry_id=entry_id,
    )


def import_public_entry(entry_id: int, snapshot: Snapshot, *, name: str, bank: float, free_transfers: int) -> UserSquad:
    nxt = snapshot.next_event() or snapshot.current_event()
    if nxt is None:
        raise RuntimeError("No gameweek available for pick import.")
    event_id = int((snapshot.previous_event() or nxt)["id"])
    with FplClient() as client:
        picks_payload = client.entry_picks(entry_id, event_id)
    ids = [int(p["element"]) for p in picks_payload.get("picks", [])]
    if len(ids) != 15:
        raise ValueError(f"Public entry {entry_id} did not return 15 picks for GW{event_id}.")
    return squad_from_ids(
        name=name,
        player_ids=ids,
        snapshot=snapshot,
        bank=bank,
        free_transfers=free_transfers,
        entry_id=entry_id,
    )
