"""Decay position calculator — Cliff, Wave, Burn curves.

Returns a 0.0-1.0 multiplier describing how much of a signal's strength is
"live" given how many days have elapsed since it was detected.

  Cliff: full strength through the peak window, then a linear drop to zero.
  Wave:  linear ramp up -> hold at peak -> linear decay to zero.
  Burn:  slow rise -> soft Gaussian peak -> slow fade.

`config` is any object/dict exposing peak_start_days, peak_end_days,
total_decay_days, decay_curve.
"""
from __future__ import annotations

import math


def _attr(config, key):
    return config[key] if isinstance(config, dict) else getattr(config, key)


def calculate_decay_position(config, days_elapsed: int) -> float:
    """Return 0.0-1.0 based on curve shape and elapsed time."""
    p_start = _attr(config, "peak_start_days") or 0
    p_end = _attr(config, "peak_end_days") or 0
    total = _attr(config, "total_decay_days") or 0
    curve = _attr(config, "decay_curve")

    if days_elapsed < 0:
        return 0.0

    if curve == "Cliff":
        # Full strength through peak, then linear drop to 0.
        if days_elapsed <= p_end:
            return 1.0
        if total <= p_end or days_elapsed >= total:
            return 0.0
        return 1.0 - (days_elapsed - p_end) / (total - p_end)

    if curve == "Wave":
        # Ramp up -> hold at peak -> decay.
        if p_start > 0 and days_elapsed < p_start:
            return days_elapsed / p_start
        if days_elapsed <= p_end:
            return 1.0
        if total <= p_end or days_elapsed >= total:
            return 0.0
        return 1.0 - (days_elapsed - p_end) / (total - p_end)

    if curve == "Burn":
        # Slow rise -> soft peak -> slow fade (Gaussian around the midpoint).
        midpoint = (p_start + p_end) / 2
        spread = (total or 1) / 4
        if spread == 0:
            return 0.0
        return max(0.0, math.exp(-((days_elapsed - midpoint) ** 2) /
                                 (2 * spread ** 2)))

    return 0.0  # unknown curve type


if __name__ == "__main__":
    cliff = {"decay_curve": "Cliff", "peak_start_days": 0,
             "peak_end_days": 30, "total_decay_days": 120}
    wave = {"decay_curve": "Wave", "peak_start_days": 120,
            "peak_end_days": 270, "total_decay_days": 540}
    burn = {"decay_curve": "Burn", "peak_start_days": 60,
            "peak_end_days": 240, "total_decay_days": 540}

    # Cliff: full strength within peak, decaying after, zero past total.
    assert calculate_decay_position(cliff, 10) == 1.0
    assert calculate_decay_position(cliff, 30) == 1.0
    assert calculate_decay_position(cliff, 120) == 0.0
    assert 0.0 < calculate_decay_position(cliff, 75) < 1.0

    # Wave: ramps from 0 at detection toward 1 at peak_start.
    assert calculate_decay_position(wave, 0) == 0.0
    assert calculate_decay_position(wave, 60) == 0.5
    assert calculate_decay_position(wave, 200) == 1.0
    assert calculate_decay_position(wave, 540) == 0.0

    # Burn: peaks softly near the midpoint of the peak window.
    mid = calculate_decay_position(burn, 150)
    edge = calculate_decay_position(burn, 0)
    assert mid > edge
    print(f"Cliff@75={calculate_decay_position(cliff,75):.2f}  "
          f"Wave@60={calculate_decay_position(wave,60):.2f}  "
          f"Burn@150={mid:.2f} Burn@0={edge:.2f}")
    print("OK: all three decay curves behave correctly.")
