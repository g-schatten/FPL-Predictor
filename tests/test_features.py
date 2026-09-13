import pytest

from fpl_predictor.features.leakage import FORBIDDEN_SAME_GW, assert_no_leakage
from fpl_predictor.models.minutes import availability


def test_leakage_guard_rejects_same_gw_outcomes() -> None:
    with pytest.raises(ValueError, match="leaked"):
        assert_no_leakage(["form", "total_points", "xpts"])


def test_allowed_feature_names_are_clean() -> None:
    assert_no_leakage(["ep_next", "form", "avail", "xmins", "fdr", "xpts"])
    assert "minutes" in FORBIDDEN_SAME_GW


def test_availability_uses_injury_and_chance() -> None:
    assert availability({"status": "a", "chance_of_playing_next_round": None}) == 1.0
    assert availability({"status": "i", "chance_of_playing_next_round": 0}) == 0.0
    assert availability({"status": "d", "chance_of_playing_next_round": 75}) == 0.75
    assert availability({"status": "s", "chance_of_playing_next_round": 100}) == 0.0
    assert availability({"status": "u"}) == 0.0
