"""Publication figures for the paper, generated from the frozen snapshot and
results/ JSONs. No network; deterministic PDF output. Writes to ``figs/``.

Figures (the D21 set; every prior generator is retired, nothing from the older
inline styling in this module survives):
  fig_event         -- two-panel de-peg event figure: (a) USDC/DAI/USDT hourly
                        prices over the full 8-17 March 2023 analysis window
                        against par and the disclosed floor, one shaded breach
                        region, event markers A/B; (b) the same three coins
                        hour-by-hour on 11 March only, plus Kraken USDC/USD
                        close and VWAP corroboration, per-hour hatched breach
                        shading with the genuine 08:57 UTC recovery hour left
                        visibly unshaded.
  fig_margin_paths  -- single-panel margin-trajectory plot (D21, replacing the
                        retired fig_floor_trough dot-and-segment plot): one
                        line per specificity-panel episode (USDC 2023, Tether
                        2019, Terra 2022 -- Paxos/USDP is excluded from this
                        panel by ruling, kept to a one-sentence body mention
                        elsewhere), each episode's own price minus its own
                        floor (cents) plotted against hours since its own
                        disclosure/anchor timestamp, -24h to +120h.

All styling comes from figstyle.py (fonts, palette, line/marker conventions,
sizing, save_figure's determinism check) -- this module contains no rcParams,
hex colours, or dash tuples of its own.
"""
from __future__ import annotations

import json
from datetime import timedelta

import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import pandas as pd

import constants
import figstyle
from constants import DATA_DIR, PKG_DIR, RESULTS_DIR

FIGS_DIR = PKG_DIR / "figs"
# tables.py imports this constant from here (not from constants.py) -- kept for
# that cross-module dependency even though neither figure builder below uses it
# itself.
TABLES_DIR = PKG_DIR.parent / "paper" / "fc27" / "tables"

# Number of labelled y-ticks passed to figstyle.set_price_axis for fig_event.
# The default (5) lands ticks at a 0.10 step for this figure's range
# (0.80/0.90/1.00/1.10), leaving no visible tick between 0.80 (outside ylim)
# and 0.90 (above the 0.88 ceiling this figure must clear). n_ticks=6 lands a
# 0.05 step (0.85/0.90/.../1.05), clearing both tick requirements -- verified
# in fig_event() by reproducing figstyle's own MaxNLocator call rather than
# assumed.
_EVENT_N_TICKS = 6


def _iso_to_dt(iso_str: str):
    """Parse an ISO-8601 timestamp (with 'Z' or '+00:00' offset) to a tz-aware
    python datetime, the type figstyle's plotting calls expect."""
    return pd.Timestamp(iso_str).tz_convert("UTC").to_pydatetime()


def _day_month_formatter(x, _pos=None) -> str:
    """'8 Mar', '17 Mar', ... -- avoids the non-portable '%-d' strftime code
    (glibc-only, not available on Windows, where this repo also builds)."""
    d = mdates.num2date(x)
    return f"{d.day} {d.strftime('%b')}"


def _merge_close_event_labels(fig, ax) -> None:
    """add_event_markers draws one correctly-positioned vertical line per event
    and one tick label per event on its secondary top axis -- both accurate,
    but on fig_event's panel (a), whose x-axis spans 9 days, event B (02:00)
    and event A (03:11, 11 March) are only 71 minutes apart, so their tick
    labels render on top of each other with no way for a reader to tell which
    line each letter names. Vertically staggering the colliding label was
    tried and rejected in QA: stacking breaks the "tick label sits directly
    above its own line" property that makes the mapping obvious for every
    OTHER marker in this figure, so a stacked "A"/"B" read as ambiguous rather
    than merely close. Fix: when two tick labels' rendered bboxes overlap,
    replace them with ONE combined label ("B,A") at their shared midpoint x --
    still a tick label (D22 permits tick labels, not a callout), and both
    vertical lines stay exactly where they belong; only the label rendering is
    merged. A no-op for panel (b), where A and B are hours apart and never
    collide."""
    secax = ax.child_axes[-1]
    fig.canvas.draw()
    labels = secax.get_xticklabels()
    if len(labels) < 2:
        return
    renderer = fig.canvas.get_renderer()
    order = sorted(range(len(labels)), key=lambda i: labels[i].get_window_extent(renderer).x0)
    ticks = list(secax.get_xticks())
    merged_ticks, merged_text = [], []
    i = 0
    while i < len(order):
        idx = order[i]
        box_i = labels[idx].get_window_extent(renderer)
        if i + 1 < len(order):
            idx2 = order[i + 1]
            box_j = labels[idx2].get_window_extent(renderer)
            if box_j.x0 < box_i.x1:  # horizontal overlap -- merge this pair
                merged_ticks.append((ticks[idx] + ticks[idx2]) / 2.0)
                merged_text.append(f"{labels[idx].get_text()},{labels[idx2].get_text()}")
                i += 2
                continue
        merged_ticks.append(ticks[idx])
        merged_text.append(labels[idx].get_text())
        i += 1
    secax.set_xticks(merged_ticks)
    secax.set_xticklabels(merged_text, fontsize=labels[0].get_fontsize(),
                           fontfamily=labels[0].get_fontfamily())
    fig.canvas.draw()


def _visible_yticks(ylim: tuple, n_ticks: int) -> list:
    """Reproduce the MaxNLocator call figstyle.set_price_axis makes internally,
    so fig_event's own assertions check what will ACTUALLY be drawn (ticks
    outside ylim are computed by the locator but never rendered), not merely
    what the locator returns unfiltered."""
    locator = mticker.MaxNLocator(nbins=n_ticks - 1, steps=[1, 2, 5])
    ticks = locator.tick_values(*ylim)
    return [t for t in ticks if ylim[0] <= t <= ylim[1]]


def fig_event(short: bool = False):
    """fig:event -- see this module's own docstring. Every plotted value is
    read live from data/price_hourly.csv and results/*.json (see the
    `sources=` dict passed to figstyle.save_figure below)."""
    price = pd.read_csv(DATA_DIR / "price_hourly.csv")
    imposs = json.loads((RESULTS_DIR / "impossibility_window.json").read_text(encoding="utf-8"))
    timing = json.loads((RESULTS_DIR / "usdt_premium_timing.json").read_text(encoding="utf-8"))
    panel_b_src = json.loads((RESULTS_DIR / "panel_11mar.json").read_text(encoding="utf-8"))

    floor = imposs["floor_worstcase"]
    assert abs(floor - (1 - constants.PHI_SVB)) < 1e-9, (
        f"floor_worstcase={floor} != 1 - PHI_SVB={1 - constants.PHI_SVB}"
    )

    a_dt = _iso_to_dt(timing["reference_points_utc"]["disclosure"])
    b_dt = _iso_to_dt(timing["peaks"]["coinbase_usdt_usd"]["timestamp_utc"])

    breach_start = _iso_to_dt(imposs["impossibility_region_usdc"]["first_breach_utc"])
    breach_end = _iso_to_dt(imposs["impossibility_region_usdc"]["last_breach_utc"])

    # ---- panel (a): full-window composite series, one per coin (each coin's
    # rows carry its OWN per-hour timestamp offset by a few seconds -- e.g.
    # USDC's first row is 1678233469, DAI's is 1678233352 -- so the three
    # series do NOT share one x-grid; plot_coin_series is therefore called
    # once per coin below, each with its own x, rather than once with one
    # shared x for all three). ----
    mask = (
        price["symbol"].isin(list(figstyle.COIN_ORDER))
        & (price["timestamp"] >= constants.WINDOW_START_S)
        & (price["timestamp"] <= constants.WINDOW_END_S)
    )
    win = price.loc[mask].copy()
    win["dt"] = pd.to_datetime(win["timestamp"], unit="s", utc=True)

    per_coin_a = {}
    for coin in figstyle.COIN_ORDER:
        sub = win[win["symbol"] == coin].sort_values("dt")
        per_coin_a[coin] = (sub["dt"].dt.to_pydatetime(), sub["price"].to_numpy())

    # ---- panel (b): 11 March composite series (same per-coin-x caveat) +
    # Kraken USDC/USD close and vwap (low is explicitly excluded -- the
    # single-trade wick is discussed in the paper body, not this figure). ----
    per_coin_b = {}
    for coin in figstyle.COIN_ORDER:
        rows = panel_b_src["panel"][f"composite_{coin}"]
        x = [_iso_to_dt(r["hour_utc"]) for r in rows]
        y = [r["price"] for r in rows]
        per_coin_b[coin] = (x, y)

    kraken_rows = panel_b_src["panel"]["kraken_usdcusd"]
    kraken_x = [_iso_to_dt(r["hour_utc"]) for r in kraken_rows]
    kraken_close = [r["close"] for r in kraken_rows]
    kraken_vwap = [r["vwap"] for r in kraken_rows]

    # ================================================================== y-range
    # Union of every plotted value across BOTH panels, plus floor and par --
    # computed once via figstyle.compute_price_ylim and applied to both axes
    # (D22: neither panel is independently rescaled).
    all_values = []
    all_values += list(win["price"])
    for coin in figstyle.COIN_ORDER:
        all_values += per_coin_b[coin][1]
    all_values += kraken_close + kraken_vwap
    all_values += [floor, 1.0]

    ylim = figstyle.compute_price_ylim(all_values)
    assert ylim[0] <= 0.86, f"ylim[0]={ylim[0]} exceeds the 0.86 task ceiling"

    usdt_window_max = win.loc[win["symbol"] == "USDT", "price"].max()
    assert ylim[1] >= usdt_window_max, (
        f"ylim[1]={ylim[1]} is below the window's USDT maximum {usdt_window_max}"
    )

    visible = _visible_yticks(ylim, _EVENT_N_TICKS)
    assert any(t <= 0.88 for t in visible), (
        f"no labelled y-tick <= 0.88 among visible ticks {visible} for ylim={ylim}"
    )
    assert any(t > usdt_window_max for t in visible), (
        f"no labelled y-tick above the USDT max {usdt_window_max} among "
        f"visible ticks {visible} for ylim={ylim}"
    )

    # ================================================================== figure
    figstyle.apply_rcparams()
    fig, (ax_a, ax_b) = figstyle.new_full_two_panel()

    # Reserve a top margin for the figure-level legend. constrained_layout does
    # not otherwise account for the secondary top x-axis add_event_markers adds
    # to panel (a) -- without this, the legend (placed at figure-fraction
    # y=1.02 by figstyle.add_shared_legend) and panel (a)'s event-letter tick
    # row (placed just above ax_a's own spine) land in the same vertical band
    # and overlap. Only the OUTER rect changes; panel (a):(b) height_ratios
    # (2.9:3.1, figstyle's own numbers) and the overall 12.2x6.4cm page size
    # are untouched.
    fig.get_layout_engine().set(rect=(0, 0, 1, 0.84))

    # ---- panel (a) ----
    lines_a = []
    for coin in figstyle.COIN_ORDER:
        x, y = per_coin_a[coin]
        lines_a += figstyle.plot_coin_series(ax_a, x, {coin: y})
    for coin, line in zip(figstyle.COIN_ORDER, lines_a):
        line.set_label(coin)

    ax_a.set_xlim(
        pd.Timestamp(constants.WINDOW_START_S, unit="s", tz="UTC").to_pydatetime(),
        pd.Timestamp(constants.WINDOW_END_S, unit="s", tz="UTC").to_pydatetime(),
    )

    figstyle.add_floor_line(ax_a, floor)
    # S-13: the short rendering darkens par. At 0.6pt in #999999 both G9 reviewers said
    # the 1.00 reference would vanish in grayscale print.
    figstyle.add_par_line(ax_a, variant=("par_dark" if short else "par"))
    figstyle.add_breach_shading(ax_a, breach_start, breach_end)
    # S-13: panel (a) carries no event labels in the short rendering. A and B are 71
    # minutes apart on a nine-day axis, so their tick labels collide and merge into an
    # unreadable "B,A"; panel (b) is the 11 March zoom where they separate. Both G9
    # reviewers reached the same conclusion about panel (a) unprompted.
    if not short:
        figstyle.add_event_markers(ax_a, [("A", a_dt), ("B", b_dt)])
        _merge_close_event_labels(fig, ax_a)

    ax_a.xaxis.set_major_locator(mdates.DayLocator())
    ax_a.xaxis.set_major_formatter(mticker.FuncFormatter(_day_month_formatter))
    ax_a.set_xlabel("date (UTC), 2023")
    ax_a.set_ylabel("price (USD)")
    figstyle.set_price_axis(ax_a, ylim, n_ticks=_EVENT_N_TICKS)
    figstyle.add_panel_label(ax_a, "a")

    # ---- panel (b) ----
    for coin in figstyle.COIN_ORDER:
        x, y = per_coin_b[coin]
        figstyle.plot_coin_series(ax_b, x, {coin: y})

    close_style = figstyle.coin_feed_style("USDC", "close")
    close_every = close_style.pop("marker_every_hours")
    ax_b.plot(kraken_x, kraken_close, markevery=close_every, **close_style)

    vwap_style = figstyle.coin_feed_style("USDC", "vwap")
    vwap_every = vwap_style.pop("marker_every_hours")
    ax_b.plot(kraken_x, kraken_vwap, markevery=vwap_every, **vwap_style)

    b_start = pd.Timestamp("2023-03-11T00:00:00Z").to_pydatetime()
    b_end = pd.Timestamp("2023-03-12T00:00:00Z").to_pydatetime()
    ax_b.set_xlim(b_start, b_end)

    figstyle.add_floor_line(ax_b, floor)
    figstyle.add_par_line(ax_b, variant=("par_dark" if short else "par"))

    # Per-hour breach shading of the COMPOSITE USDC firing hours (not one
    # span). Each firing row shades from its own hour to the NEXT row's hour
    # (or +1h for the last row); a non-firing row (e.g. 08:57, whose coverage-
    # gap check confirms it is a genuine recovery hour, not a data gap) is
    # simply never the start of a shaded span, which is what leaves the
    # visible unshaded gap -- no special-casing of that hour.
    usdc_rows_b = panel_b_src["panel"]["composite_USDC"]
    for i, row in enumerate(usdc_rows_b):
        if not row["firing"]:
            continue
        start = _iso_to_dt(row["hour_utc"])
        if i + 1 < len(usdc_rows_b):
            end = _iso_to_dt(usdc_rows_b[i + 1]["hour_utc"])
        else:
            end = start + timedelta(hours=1)
        figstyle.add_breach_shading(ax_b, start, end)

    figstyle.add_event_markers(ax_b, [("A", a_dt), ("B", b_dt)])

    ax_b.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    ax_b.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_b.set_xlabel("hour (UTC), 11 March 2023")
    ax_b.set_ylabel("price (USD)")
    figstyle.set_price_axis(ax_b, ylim, n_ticks=_EVENT_N_TICKS)
    figstyle.add_panel_label(ax_b, "b")

    # ---- shared legend: the 3 coin series only. Kraken close/vwap omitted to
    # keep one row legible at 7pt in a 12.2cm-wide figure -- their thin lines
    # and open circle/triangle markers hugging the USDC line are visually
    # self-evident without a separate legend entry. Floor/par are never
    # labelled here (caption-only convention, matching every reference line in
    # this style system). ----
    figstyle.add_shared_legend(fig, (ax_a, ax_b))

    result = figstyle.save_figure(
        fig, "fig_event_short" if short else "fig_event",
        sources={
            "data/price_hourly.csv": ["symbol", "timestamp", "price"],
            "results/impossibility_window.json": [
                "floor_worstcase",
                "impossibility_region_usdc.first_breach_utc",
                "impossibility_region_usdc.last_breach_utc",
            ],
            "results/usdt_premium_timing.json": [
                "reference_points_utc.disclosure",
                "peaks.coinbase_usdt_usd.timestamp_utc",
            ],
            "results/panel_11mar.json": [
                "panel.composite_USDC[*].hour_utc,price,firing",
                "panel.composite_DAI[*].hour_utc,price",
                "panel.composite_USDT[*].hour_utc,price",
                "panel.kraken_usdcusd[*].hour_utc,close,vwap",
                "coverage_gap_check_08_57_utc.genuine_data_gap",
            ],
        },
    )
    return result


def _find_combo(combinations: list[dict], **match) -> dict:
    """First entry in `combinations` whose fields match every kwarg exactly.
    Raises KeyError (loudly) rather than silently returning nothing, so a
    typo'd label or a JSON schema change breaks the build instead of drawing a
    wrong row."""
    for c in combinations:
        if all(c.get(k) == v for k, v in match.items()):
            return c
    raise KeyError(f"no combination matching {match!r} in the given list")


def fig_margin_paths():
    """fig:margin_paths -- see this module's own docstring. Replaces the
    retired fig_floor_trough (D21): rather than a single static floor-vs-
    trough dot-and-line comparison per episode, this figure draws each
    episode's full margin TRAJECTORY -- price minus its own floor, in cents --
    against hours since its own disclosure/anchor timestamp, -24h to +120h.
    Every plotted value is read live from data/*.csv and results/*.json (see
    the `sources=` dict passed to figstyle.save_figure below)."""
    price = pd.read_csv(DATA_DIR / "price_hourly.csv")
    timing = json.loads((RESULTS_DIR / "usdt_premium_timing.json").read_text(encoding="utf-8"))
    imposs = json.loads((RESULTS_DIR / "impossibility_window.json").read_text(encoding="utf-8"))
    spec = json.loads((RESULTS_DIR / "specificity_panel.json").read_text(encoding="utf-8"))
    terra_result = json.loads((RESULTS_DIR / "second_event_terra.json").read_text(encoding="utf-8"))

    WINDOW_LO_H, WINDOW_HI_H = -24.0, 120.0

    # ---- Episode 1: USDC, March 2023 -- composite series, same read/filter
    # pattern as fig_event(). ----
    usdc = price.loc[price["symbol"] == "USDC"].copy()
    anchor_usdc_s = _iso_to_dt(timing["reference_points_utc"]["disclosure"]).timestamp()
    usdc["hours"] = (usdc["timestamp"] - anchor_usdc_s) / 3600.0
    usdc = usdc[(usdc["hours"] >= WINDOW_LO_H) & (usdc["hours"] <= WINDOW_HI_H)].sort_values("hours")

    floor_usdc = 1 - constants.PHI_SVB
    assert abs(imposs["floor_worstcase"] - floor_usdc) < 1e-9, (
        f"floor_worstcase={imposs['floor_worstcase']} != 1 - PHI_SVB={floor_usdc}"
    )
    margin_usdc = (usdc["price"] - floor_usdc) * 100.0

    # ---- Episode 2: Tether, April-May 2019 -- Kraken USDT/USD hourly CLOSE.
    # Deliberately NOT `low` (Table 3's headline single-point-trough
    # convention): `low` is a per-hour EXTREME wick, right for a worst-print
    # comparison but a noisy, spiky path. This figure's job is showing
    # trajectory SHAPE, not re-asserting a specific trough number, so `close`
    # is the deliberately smoother, representative series. This is a genuine,
    # documented divergence from Table 3's convention -- do not "fix" it back
    # to `low` without understanding why. ----
    tether = pd.read_csv(DATA_DIR / "n1" / "kraken_usdtusd_2019" / "hourly.csv")
    tether_ts_s = pd.to_datetime(tether["hour_utc"], utc=True).astype("int64") // 10**9
    tether["hours"] = (tether_ts_s - constants.TETHER_2019_DISCLOSURE_S) / 3600.0
    tether = tether[(tether["hours"] >= WINDOW_LO_H) & (tether["hours"] <= WINDOW_HI_H)].sort_values("hours")

    row2 = spec["row2_tether_2019"]
    combo_ceiling = _find_combo(row2["combinations"], phi_label="phi_900M_credit_line_ceiling")
    combo_drawn = _find_combo(row2["combinations"], phi_label="phi_700M_amount_already_drawn")
    floor2_lo, floor2_hi = combo_ceiling["floor"], combo_drawn["floor"]
    floor2_mid = (floor2_lo + floor2_hi) / 2.0
    margin_tether = (tether["close"] - floor2_mid) * 100.0
    band_halfwidth = ((floor2_hi - floor2_lo) / 2.0) * 100.0
    band_lo = margin_tether - band_halfwidth
    band_hi = margin_tether + band_halfwidth

    # ---- Episode 3: Terra, May 2022 -- composite USDT leg (NOT USDC; D21 is
    # explicit this control is USDT-denominated), phi=0. Terra has NO actual
    # disclosure event (phi=0 BY CONSTRUCTION -- see second_event_terra.json's
    # own degenerate_caveat), so this series' x-axis origin reuses the
    # existing canonical TERRA_WINDOW_START_S window-start constant as its
    # "hours since X" anchor, rather than inventing a disclosure timestamp
    # that does not exist -- a deliberate, documented substitution specific to
    # this one degenerate control, not an oversight. ----
    terra_price = pd.read_csv(DATA_DIR / "terra_price_hourly.csv")
    terra_usdt = terra_price.loc[terra_price["symbol"] == "USDT"].copy()
    terra_usdt["hours"] = (terra_usdt["timestamp"] - constants.TERRA_WINDOW_START_S) / 3600.0
    terra_usdt = terra_usdt[
        (terra_usdt["hours"] >= WINDOW_LO_H) & (terra_usdt["hours"] <= WINDOW_HI_H)
    ].sort_values("hours")
    # DATA COVERAGE GAP (confirmed, not a bug to fix): the frozen USDT rows
    # start at ~TERRA_WINDOW_START_S itself (~t=+0.03h), not -24h -- there is
    # no real data for this episode's -24h..~0h portion. Nothing is
    # extrapolated or fabricated to fill it; the line simply starts wherever
    # the real data starts, which is the honest rendering of a real coverage
    # constraint, not a rendering error.

    floor_terra = terra_result["floor_worstcase"]
    assert floor_terra == 1.0, f"floor_worstcase={floor_terra} != 1.0 (Terra is phi=0, floor=par)"
    margin_terra = (terra_usdt["price"] - floor_terra) * 100.0

    # ================================================================== y-range
    all_values = (list(margin_usdc) + list(margin_tether) + list(band_lo) + list(band_hi)
                  + list(margin_terra) + [0.0])
    ylim = figstyle.compute_price_ylim(all_values, tick_step=5.0, margin_ticks=1)

    # ================================================================== figure
    figstyle.apply_rcparams()
    fig, ax = figstyle.new_half_height()

    # Zero on the y-axis IS the floor by construction (margin = price - own
    # floor); reuse the floor reference-line style (REFERENCE_STYLE['floor']
    # via add_floor_line) at value=0.0 -- NOT add_par_line, which draws at
    # price=$1.00, the wrong axis here. D21: only ONE reference line on this
    # figure (zero/floor); no separate par-minus-floor line is drawn.
    figstyle.add_floor_line(ax, 0.0)

    # Tether's floor uncertainty band -- translated into margin space around
    # its own line (not a static band around y=0), drawn BELOW the coin lines
    # (zorder 2, under plot_coin_series's zorder=3) so every line stays crisp
    # on top. No edge, no label: pure graphics, D22-compliant (no in-axes
    # text). Does not collide with the USDC or Terra lines -- the band sits at
    # ~22-34 cents while USDC ranges -4 to +9 cents and Terra -1 to +1 cent.
    ax.fill_between(tether["hours"], band_lo, band_hi, color=figstyle.PALETTE["dai"],
                     alpha=0.15, linewidth=0, zorder=2)

    # Episode identity is carried by the three EXISTING COIN_STYLE roles
    # directly, not a new figure-specific style: this figure has three
    # EPISODES but only two distinct COINS (USDC once; USDT twice, as
    # Tether-2019 and Terra-2022). USDC-2023 -> COIN_STYLE['USDC'] (solid,
    # genuinely the same coin). Tether-2019 -> COIN_STYLE['DAI'] (dashed,
    # vermillion) -- REPURPOSED for episode identity; this is NOT literally
    # DAI, it is Tether/USDT 2019, borrowing DAI's dash+colour role so the
    # figure needs only the 3 existing hues rather than inventing a 4th
    # (figstyle's own "two figures using three hues ... read as one system"
    # principle). Terra-2022 -> COIN_STYLE['USDT'] (dotted, green) --
    # coincidentally ALSO accurate, since Terra's series genuinely is USDT.
    ax.plot(usdc["hours"], margin_usdc, zorder=3, **figstyle.COIN_STYLE["USDC"])
    ax.plot(tether["hours"], margin_tether, zorder=3, **figstyle.COIN_STYLE["DAI"])
    ax.plot(terra_usdt["hours"], margin_terra, zorder=3, **figstyle.COIN_STYLE["USDT"])

    ax.set_xlim(WINDOW_LO_H, WINDOW_HI_H)
    ax.xaxis.set_major_locator(mticker.FixedLocator([-24, 0, 24, 48, 72, 96, 120]))
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    ax.set_xlabel("hours since disclosure")

    ax.set_ylim(*ylim)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5, steps=[1, 2, 5]))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    ax.set_ylabel("margin (cents)")

    result = figstyle.save_figure(
        fig, "fig_margin_paths",
        sources={
            "data/price_hourly.csv": ["symbol", "timestamp", "price"],
            "data/n1/kraken_usdtusd_2019/hourly.csv": ["hour_utc", "close"],
            "data/terra_price_hourly.csv": ["symbol", "timestamp", "price"],
            "results/usdt_premium_timing.json": ["reference_points_utc.disclosure"],
            "results/impossibility_window.json": ["floor_worstcase"],
            "results/specificity_panel.json": [
                "row2_tether_2019.combinations[phi_label=phi_900M_credit_line_ceiling].floor",
                "row2_tether_2019.combinations[phi_label=phi_700M_amount_already_drawn].floor",
            ],
            "results/second_event_terra.json": ["floor_worstcase"],
        },
    )
    return result



def fig_event_short():
    """The short paper's rendering of fig_event. See fig_event's `short` parameter."""
    return fig_event(short=True)


def main():
    """Regenerate every figure this module defines. Each fig_* function is
    responsible for its own save_figure() call and its own sources sidecar.
    Function list is maintained here (not by each builder editing main()
    concurrently) to avoid a multi-writer collision on this one function."""
    FIGS_DIR.mkdir(parents=True, exist_ok=True)
    produced = []
    # fig_event is rendered twice: the regular paper's, and a short-paper
    # rendering with S-13's legibility fixes. Same builder, same frozen data.
    for name in ("fig_event", "fig_event_short", "fig_margin_paths"):
        fn = globals().get(name)
        if fn is None:
            print(f"WARNING: {name} not yet defined in figures.py -- skipped")
            continue
        result = fn()
        produced.append((name, result))
        print(f"{name}: {result}")
    print(f"Wrote {len(produced)} figure(s) to {FIGS_DIR}")
    return produced


if __name__ == "__main__":
    main()
