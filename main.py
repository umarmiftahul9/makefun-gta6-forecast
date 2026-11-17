"""GTA VI launch-day Twitch CCU forecaster -- variant F (heavy-tail quantiles).

Log-scale quantile forecaster, anchored on the first hour's print.

Idea, in one paragraph: the first hour's viewer count sets the scale of the
whole day, and the *shape* of the day -- how the audience dips in the small
hours and then climbs again as each region wakes up and unlocks -- is learned
at run time from the 38 past big launches shipped inside each case file.
For every forecast hour we take the median, across those launches, of
log(viewers_h / viewers_hour1). That median is the log-median of the hour.
What makes this variant different is the spread: it is deliberately wide
and honest. The outer quantiles use heavy-tail multipliers and a spread
fitted from the launches' own disagreement (their median absolute
deviation), floored so the band never pretends to be narrow and capped so
one freak launch cannot blow it up. We pay a little pinball loss on
ordinary hours in exchange for never running out of band when the day
surges or sags.

Only the Python standard library is used. No network, no randomness, no
clock reads: the same input always produces the same bytes.
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Heavy-tail multipliers for the five levels: the outer pair sits far
# outside the normal 1.645, so a surprise in either direction stays
# inside the 5%-95% band; the inner pair stays near the quartiles.
Z_HEAVY = [-2.33, -0.95, 0.0, 0.95, 2.33]
# Spread of the log-ratios, fitted per hour, is never allowed below this
# (a launch day is never that predictable) or above this (one freak
# launch must not set the band for everybody).
SIGMA_FLOOR = 0.32
SIGMA_CAP = 0.60
# A comparable only counts as "already live at hour 1" when its first
# hour already reached at least this share of its own release-day peak.
# Launches still dark at hour 1 (a single global unlock later in the
# day) follow a different shape and would drag the median up.
LIVE_SHARE = 0.10
MIN_LIVE_CURVES = 8
MIN_HOURS_PRESENT = 20


def _parse_time(text):
    """ISO-8601 timestamp -> aware datetime (accepts a trailing Z)."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _round2(value):
    """Round to 2 decimals, halves away from zero, returning int when whole."""
    scaled = value * 100.0
    whole = math.floor(scaled + 0.5)
    out = whole / 100.0
    return int(out) if out == int(out) else out


def _day_curve(comp):
    """Release-day hourly viewers of one comparable, keyed 0..23.

    Returns None when the curve cannot anchor on hour 1 (no hour-0 point
    or too sparse to trust).
    """
    try:
        start = _parse_time(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    by_hour = {}
    for point in comp.get("hourly") or []:
        try:
            viewers = point["viewers"]
            at = _parse_time(point["from"])
        except (KeyError, TypeError, ValueError):
            continue
        if viewers is None or viewers <= 0:
            continue
        offset = int((at - start).total_seconds() // 3600)
        if 0 <= offset < 24:
            by_hour[offset] = float(viewers)
    if 0 not in by_hour or len(by_hour) < MIN_HOURS_PRESENT:
        return None
    return by_hour


def _fit_shape(comparables):
    """Per-hour (median log-ratio to hour 1, spread) fitted from comparables.

    Returns two dicts keyed by hour index 1..23. Hours with too few
    launches fall back to the nearest fitted hour, then to a flat median.
    """
    curves = []
    for comp in comparables or []:
        curve = _day_curve(comp)
        if curve is not None:
            curves.append(curve)
    if not curves:
        return {}, {}
    live = [c for c in curves if c[0] >= LIVE_SHARE * max(c.values())]
    pool = live if len(live) >= MIN_LIVE_CURVES else curves
    medians = {}
    sigmas = {}
    for hour in range(1, 24):
        ratios = [math.log(c[hour] / c[0]) for c in pool if hour in c]
        if len(ratios) < 5:
            continue
        med = _median(ratios)
        mad = _median([abs(r - med) for r in ratios])
        medians[hour] = med
        sigmas[hour] = min(SIGMA_CAP, max(SIGMA_FLOOR, 1.4826 * mad))
    # Smooth the median shape with a 3-hour moving average: launch curves
    # are noisy hour to hour, the underlying shape is not.
    smooth = {}
    for hour in range(1, 24):
        near = [medians[k] for k in (hour - 1, hour, hour + 1) if k in medians]
        if near:
            smooth[hour] = sum(near) / len(near)
    for hour in range(1, 24):
        if hour not in smooth:
            # Walk outward to the nearest fitted hour; flat if none fitted.
            for step in range(1, 24):
                if hour - step in medians:
                    smooth[hour] = medians[hour - step]
                    break
                if hour + step in medians:
                    smooth[hour] = medians[hour + step]
                    break
            else:
                smooth[hour] = 0.0
        if hour not in sigmas:
            sigmas[hour] = 0.45
    return smooth, sigmas


def forecast_case(case):
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError("case has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))
    medians, sigmas = _fit_shape(case.get("comparables"))
    # The case always lists hours 2..24; fall back to them if it ever omits
    # the list, so a thin case still gets a complete forecast.
    rows_in = case.get("forecast") or [{"hour": h} for h in range(2, 25)]
    rows = []
    for row in rows_in:
        hour = row["hour"]
        offset = hour - 1  # hour 2 is the first step after the anchor hour
        med = medians.get(offset, 0.0)
        sig = sigmas.get(offset, 0.45)
        quantiles = []
        for z in Z_HEAVY:
            value = p1 * math.exp(med + z * sig)
            value = min(1e9, max(1.0, value))
            quantiles.append(_round2(value))
        # Guarantee non-decreasing even after rounding.
        for i in range(1, len(quantiles)):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        rows.append({"hour": hour, "q": quantiles})
    rows.sort(key=lambda r: r["hour"])
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
