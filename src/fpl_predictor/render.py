from __future__ import annotations

from rich.console import Console
from rich.table import Table

from fpl_predictor.data.snapshots import Snapshot
from fpl_predictor.optimize.transfers import TransferPlan
from fpl_predictor.optimize.wildcard import WildcardPlan
from fpl_predictor.squad.store import UserSquad

console = Console()


def print_snapshot(snapshot: Snapshot) -> None:
    nxt = snapshot.next_event()
    cur = snapshot.current_event()
    players = snapshot.players()
    injured = sum(1 for p in players if p.get("status") == "i")
    doubtful = sum(1 for p in players if p.get("status") == "d")
    risen = sum(1 for p in players if int(p.get("cost_change_event") or 0) > 0)
    fallen = sum(1 for p in players if int(p.get("cost_change_event") or 0) < 0)
    console.print(f"[bold]Snapshot[/bold] {snapshot.path}")
    console.print(f"Pulled {snapshot.meta['pulled_at']}")
    if cur:
        console.print(f"Current: GW{cur['id']}  deadline {cur.get('deadline_time')}  finished={cur.get('finished')}")
    if nxt:
        console.print(f"Next:    GW{nxt['id']}  deadline {nxt.get('deadline_time')}")
    console.print(
        f"Players {len(players)}  |  injured {injured}  doubtful {doubtful}  |  "
        f"price up {risen}  down {fallen} this GW"
    )


def _role(pick) -> str:
    if pick.captain:
        return "C"
    if pick.vice:
        return "V"
    if pick.starter:
        return ""
    return f"B{pick.bench_order}"


def print_squad_plan(plan: WildcardPlan, *, title: str) -> None:
    table = Table(title=title, show_lines=False)
    table.add_column("Role", width=4)
    table.add_column("Pos", width=4)
    table.add_column("Player")
    table.add_column("Team", width=5)
    table.add_column("£", justify="right")
    table.add_column("xPts", justify="right")
    table.add_column("xMin", justify="right")
    table.add_column("Avail", justify="right")
    table.add_column("Risk")
    ordered = plan.starters + plan.bench
    for pick in ordered:
        player = pick.player
        risk = ", ".join(player.risk_flags)
        if player.news:
            risk = f"{risk} | {player.news}" if risk else player.news
        table.add_row(
            _role(pick),
            player.position,
            player.web_name,
            player.team_short,
            f"{player.now_cost / 10:.1f}",
            f"{player.xpts:.2f}",
            f"{player.xmins:.0f}",
            f"{int(player.availability * 100)}%",
            risk,
        )
    console.print(table)
    console.print(
        f"Solver [bold]{plan.status}[/bold]  |  XI+captain horizon xPts {plan.horizon_xpts:.2f}  |  "
        f"bank £{plan.bank:.1f}m"
    )


def print_transfers(plan: TransferPlan) -> None:
    if not plan.transfers:
        console.print("[bold]Hold[/bold] — no transfer beats doing nothing within the hit limit.")
    else:
        table = Table(title="Recommended transfers")
        table.add_column("Out")
        table.add_column("Sell", justify="right")
        table.add_column("In")
        table.add_column("Buy", justify="right")
        table.add_column("xPts in-out", justify="right")
        for move in plan.transfers:
            delta = move.player_in.xpts - move.player_out.xpts
            table.add_row(
                f"{move.player_out.web_name} ({move.player_out.team_short})",
                f"£{move.sell / 10:.1f}",
                f"{move.player_in.web_name} ({move.player_in.team_short})",
                f"£{move.buy / 10:.1f}",
                f"{delta:+.2f}",
            )
        console.print(table)
    console.print(
        f"Hits {plan.hits} (−{plan.hit_cost} pts)  |  hold xPts {plan.do_nothing_xpts:.2f}  |  "
        f"new XI+C {plan.wildcard.horizon_xpts:.2f}  |  net vs hold {plan.delta_vs_hold:+.2f}  |  "
        f"bank £{plan.bank:.1f}m"
    )
    print_squad_plan(plan.wildcard, title="Squad after transfers")


def print_saved_squad(squad: UserSquad, snapshot: Snapshot) -> None:
    by_id = {int(p["id"]): p for p in snapshot.players()}
    table = Table(title=f"Saved squad: {squad.name}")
    table.add_column("ID", justify="right")
    table.add_column("Player")
    table.add_column("£ now", justify="right")
    table.add_column("Sell", justify="right")
    table.add_column("Status")
    table.add_column("News")
    for pid in squad.player_ids:
        raw = by_id.get(pid, {})
        table.add_row(
            str(pid),
            str(raw.get("web_name") or pid),
            f"{int(raw.get('now_cost') or 0) / 10:.1f}",
            f"{squad.selling_prices.get(pid, 0) / 10:.1f}",
            str(raw.get("status") or "?"),
            str(raw.get("news") or ""),
        )
    console.print(table)
    console.print(f"Bank £{squad.bank:.1f}m  |  FT {squad.free_transfers}  |  saved {squad.saved_at or '—'}")
