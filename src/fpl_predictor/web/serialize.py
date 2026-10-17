from __future__ import annotations

from typing import Any

from fpl_predictor.data.snapshots import Snapshot
from fpl_predictor.explain import TrustNote
from fpl_predictor.optimize.transfers import TransferPlan
from fpl_predictor.optimize.wildcard import SquadPick, WildcardPlan
from fpl_predictor.squad.store import UserSquad

STATUS_LABEL = {
    "a": "available",
    "d": "doubtful",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable",
}


def pick_json(pick: SquadPick) -> dict[str, Any]:
    player = pick.player
    return {
        "id": player.player_id,
        "name": player.web_name,
        "team": player.team_short,
        "position": player.position,
        "element_type": player.element_type,
        "cost": round(player.now_cost / 10, 1),
        "xpts": round(player.xpts, 2),
        "xmins": round(player.xmins),
        "availability": round(player.availability * 100),
        "status": player.status,
        "status_label": STATUS_LABEL.get(player.status, player.status),
        "news": player.news,
        "flags": player.risk_flags,
        "selected_by": player.selected_by,
        "starter": pick.starter,
        "captain": pick.captain,
        "vice": pick.vice,
        "bench_order": pick.bench_order,
        "by_gw": {str(gw): round(pts, 2) for gw, pts in player.xpts_by_gw.items()},
        "opponents": player.opponents,
        "breakdown": player.breakdown,
    }


def plan_json(plan: WildcardPlan) -> dict[str, Any]:
    return {
        "status": plan.status,
        "horizon_xpts": round(plan.horizon_xpts, 2),
        "bank": round(plan.bank, 1),
        "spend": round(sum(p.player.now_cost for p in plan.picks) / 10, 1),
        "starters": [pick_json(p) for p in plan.starters],
        "bench": [pick_json(p) for p in plan.bench],
    }


def transfer_plan_json(plan: TransferPlan) -> dict[str, Any]:
    return {
        "squad": plan_json(plan.wildcard),
        "hits": plan.hits,
        "hit_cost": plan.hit_cost,
        "hold_xpts": round(plan.do_nothing_xpts, 2),
        "delta_vs_hold": round(plan.delta_vs_hold, 2),
        "bank": round(plan.bank, 1),
        "free_transfers_used": plan.free_transfers_used,
        "moves": [
            {
                "out": {
                    "name": move.player_out.web_name,
                    "team": move.player_out.team_short,
                    "position": move.player_out.position,
                    "price": round(move.sell / 10, 1),
                    "xpts": round(move.player_out.xpts, 2),
                    "news": move.player_out.news,
                },
                "in": {
                    "name": move.player_in.web_name,
                    "team": move.player_in.team_short,
                    "position": move.player_in.position,
                    "price": round(move.buy / 10, 1),
                    "xpts": round(move.player_in.xpts, 2),
                    "news": move.player_in.news,
                },
                "gain": round(move.player_in.xpts - move.player_out.xpts, 2),
            }
            for move in plan.transfers
        ],
    }


def note_json(note: TrustNote) -> dict[str, Any]:
    return {
        "pulled_at": note.pulled_at,
        "gameweek": note.gameweek,
        "deadline": note.deadline,
        "solver_status": note.solver_status,
        "horizon": note.horizon,
        "span": note.span,
        "legality": note.legality,
        "basis": note.basis,
        "risky_starters": note.risky_starters,
        "risk_line": note.risk_line,
    }


def snapshot_json(snapshot: Snapshot) -> dict[str, Any]:
    players = snapshot.players()
    current = snapshot.current_event()
    nxt = snapshot.next_event()
    rules = snapshot.rules
    teams = snapshot.teams_by_id()

    def count(status: str) -> int:
        return sum(1 for p in players if p.get("status") == status)

    movers = [p for p in players if int(p.get("cost_change_event") or 0) != 0]
    movers.sort(key=lambda p: (-abs(int(p["cost_change_event"])), -int(p["now_cost"])))
    flagged = [p for p in players if p.get("news") and p.get("status") != "a"]
    flagged.sort(key=lambda p: -int(p["now_cost"]))

    return {
        "pulled_at": snapshot.meta.get("pulled_at"),
        "current_gw": current.get("id") if current else None,
        "next_gw": nxt.get("id") if nxt else None,
        "next_deadline": nxt.get("deadline_time") if nxt else None,
        "players": len(players),
        "injured": count("i"),
        "doubtful": count("d"),
        "suspended": count("s"),
        "price_up": sum(1 for p in players if int(p.get("cost_change_event") or 0) > 0),
        "price_down": sum(1 for p in players if int(p.get("cost_change_event") or 0) < 0),
        "budget": round(rules.budget / 10, 1),
        "team_limit": rules.team_limit,
        "movers": [
            {
                "name": p["web_name"],
                "team": str(teams.get(int(p["team"]), {}).get("short_name") or ""),
                "delta": round(int(p["cost_change_event"]) / 10, 1),
                "cost": round(int(p["now_cost"]) / 10, 1),
            }
            for p in movers[:8]
        ],
        "flagged": [
            {
                "name": p["web_name"],
                "cost": round(int(p["now_cost"]) / 10, 1),
                "status_label": STATUS_LABEL.get(p.get("status"), p.get("status")),
                "news": p.get("news"),
            }
            for p in flagged[:6]
        ],
    }


def squad_json(squad: UserSquad, snapshot: Snapshot) -> dict[str, Any]:
    by_id = {int(p["id"]): p for p in snapshot.players()}
    return {
        "name": squad.name,
        "bank": squad.bank,
        "free_transfers": squad.free_transfers,
        "entry_id": squad.entry_id,
        "saved_at": squad.saved_at,
        "players": [
            {
                "id": pid,
                "name": str(by_id.get(pid, {}).get("web_name") or pid),
                "team_id": by_id.get(pid, {}).get("team"),
                "cost": round(int(by_id.get(pid, {}).get("now_cost") or 0) / 10, 1),
                "sell": round(squad.selling_prices.get(pid, 0) / 10, 1),
                "status_label": STATUS_LABEL.get(by_id.get(pid, {}).get("status"), "?"),
                "news": by_id.get(pid, {}).get("news") or "",
            }
            for pid in squad.player_ids
        ],
    }
