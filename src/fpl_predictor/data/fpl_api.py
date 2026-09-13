from __future__ import annotations

import time
from typing import Any

import httpx

BASE_URL = "https://fantasy.premierleague.com/api"
USER_AGENT = "fpl-predictor/0.1 (+local research tool)"


class FplClient:
    def __init__(self, timeout: float = 30.0, retries: int = 3) -> None:
        self._timeout = timeout
        self._retries = retries
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FplClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_json(self, path: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = self._client.get(path)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"FPL API failed for {path}: {last_error}") from last_error

    def bootstrap(self) -> dict[str, Any]:
        return self.get_json("/bootstrap-static/")

    def fixtures(self) -> list[dict[str, Any]]:
        return self.get_json("/fixtures/")

    def event_status(self) -> dict[str, Any]:
        return self.get_json("/event-status/")

    def set_piece_notes(self) -> Any:
        return self.get_json("/team/set-piece-notes/")

    def element_summary(self, player_id: int) -> dict[str, Any]:
        return self.get_json(f"/element-summary/{player_id}/")

    def entry(self, manager_id: int) -> dict[str, Any]:
        return self.get_json(f"/entry/{manager_id}/")

    def entry_history(self, manager_id: int) -> dict[str, Any]:
        return self.get_json(f"/entry/{manager_id}/history/")

    def entry_picks(self, manager_id: int, event_id: int) -> dict[str, Any]:
        return self.get_json(f"/entry/{manager_id}/event/{event_id}/picks/")
