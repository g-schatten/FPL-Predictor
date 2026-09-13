from __future__ import annotations

from fpl_predictor.models.train import load_booster, model_exists


def load_model_adjustments() -> dict[int, float]:
    """Reserved for blending a trained residual model into live projections.

    Live recommendations always start from the deadline-safe snapshot engine.
    A trained model is reported by `fpl train` / `fpl evaluate`; it is not
    allowed to silently overwrite injury or price information.
    """
    if not model_exists() or load_booster() is None:
        return {}
    return {}
