from fpl_predictor.data.rules import parse_rules, selling_price


def test_selling_price_half_profit() -> None:
    assert selling_price(70, 70) == 70
    assert selling_price(70, 68) == 68
    assert selling_price(70, 75) == 72
    assert selling_price(70, 76) == 73


def test_parse_live_settings_shape() -> None:
    bootstrap = {
        "game_settings": {
            "squad_squadsize": 15,
            "squad_squadplay": 11,
            "squad_team_limit": 3,
            "squad_total_spend": 1000,
            "transfers_sell_on_fee": 0.5,
            "max_extra_free_transfers": 4,
            "transfers_cap": 20,
        },
        "element_types": [
            {"id": 1, "singular_name_short": "GKP", "squad_select": 2, "squad_min_play": 1, "squad_max_play": 1},
            {"id": 2, "singular_name_short": "DEF", "squad_select": 5, "squad_min_play": 3, "squad_max_play": 5},
            {"id": 3, "singular_name_short": "MID", "squad_select": 5, "squad_min_play": 2, "squad_max_play": 5},
            {"id": 4, "singular_name_short": "FWD", "squad_select": 3, "squad_min_play": 1, "squad_max_play": 3},
        ],
        "chips": [{"name": "wildcard", "start_event": 2, "stop_event": 19}],
    }
    rules = parse_rules(bootstrap)
    assert rules.budget == 1000
    assert rules.positions[2].min_play == 3
    assert rules.chips[0].stop_event == 19
