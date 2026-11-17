[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/umarmiftahul9/makefun-gta6-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/umarmiftahul9/makefun-gta6-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

# GTA VI Twitch CCU forecaster — variant F (heavy-tail quantiles)

Entry for `gta6-twitch-ccu-forecast-01`: forecast Grand Theft Auto VI's
Twitch concurrent viewers, hour by hour, for hours 2–24 of release day
(2026-11-19 UTC), as five quantiles per hour, from the first hour's print.

## Model

A log-scale quantile forecaster anchored on the hour-1 print. The shape of
the day is fitted at run time from the past big launches shipped inside
each case file: for every forecast hour, the median across those launches
of `log(viewers_h / viewers_hour1)` sets the log-median. Launches that were
still dark at hour 1 (a single global unlock later in the day) are left
out of the fit, because they follow a different shape from a launch that
was already live at hour 1, like GTA VI's rolling midnight unlock.

What makes this variant different is the spread: it is deliberately wide
and honest. The outer quantiles (5% and 95%) use heavy-tail multipliers
(±2.33 instead of the normal ±1.645), and the per-hour spread is fitted
from the launches' own disagreement (their median absolute deviation),
floored at 0.32 and capped at 0.60 log units. It pays a little pinball
loss on ordinary hours in exchange for never running out of band when the
day surges or sags. The median itself stays the best point prediction.

## Run

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13 standard library only, no network, deterministic: two runs on
the same input write byte-identical output. Reads every `*.in` in the
input directory and writes one `<id>.out` per case.

## Local validation

Leave-one-out over the 38 comparables shipped in the practice cases
(each launch held out in turn, forecast from the other 37, scored with
the contest's log-scale pinball loss against its real release day):

- all 37 launches: this model **0.84** vs flat baseline **1.14**
- the 27 launches already live at hour 1 (the GTA VI-like subset):
  this model **0.26** vs flat baseline **0.46**

The flat baseline is the house persistence forecast (every quantile equal
to the hour-1 print). The model beats it clearly on both sets.
