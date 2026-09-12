"""Smoke test: figures.py produces exactly the D21 figure set (fig_event,
fig_margin_paths), each deterministic, each with a sources sidecar, each at
its budgeted height, each free of in-axes text. Every prior generator
(fig_11mar_panel, fig_depeg_paths, fig_supply, fig_floor_trough, and the
earlier-cut fig3_phi_rho_sweep / fig4_model_validation / fig1_depeg_paths /
fig2_supply_outflow) is gone -- re-adding any of them needs a fresh ruling,
not a silent revert. fig_event's own budget moved 6.4->8.6cm and
fig_floor_trough was replaced by fig_margin_paths (4.0cm) under D21, both
already reflected below."""
import sys
from pathlib import Path

import fitz

import figures
import figstyle
from constants import PKG_DIR

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import figqa  # noqa: E402  (path insert must precede this import)

# fig_event_short is the short paper's rendering of fig_event: same builder, same
# frozen data, with G10's legibility fixes (no merged event tick in panel (a), a
# darker par line). It is a separate stem because the regular paper is frozen and
# shares this builder.
EXPECTED_STEMS = ["fig_event", "fig_event_short", "fig_margin_paths"]
HEIGHT_BUDGET_CM = {"fig_event": 8.6, "fig_event_short": 8.6, "fig_margin_paths": 4.0}
CUT_OR_ORPHANED = [
    "fig_11mar_panel", "fig_depeg_paths", "fig_supply", "fig_floor_trough",
    "fig3_phi_rho_sweep", "fig4_model_validation",
    "fig1_depeg_paths", "fig2_supply_outflow",
]


def test_every_current_figure_produced_and_deterministic():
    results = figures.main()
    produced = dict(results)
    assert set(produced) == set(EXPECTED_STEMS), (
        f"figures.main() produced {sorted(produced)}, expected exactly {sorted(EXPECTED_STEMS)}"
    )
    figs_dir = PKG_DIR / "figs"
    for stem, result in produced.items():
        f = Path(result["path"])
        assert f == figs_dir / f"{stem}.pdf"
        assert f.exists() and f.stat().st_size > 0, f"{stem}.pdf missing or empty"
        # figstyle.save_figure asserts determinism internally (raises rather than
        # falling back to a non-deterministic format) -- a successful return here
        # already proves it. Re-verified independently below via a second call.


def test_determinism_via_double_render():
    """Calls each builder TWICE (independent Python-level calls, not just
    save_figure's own internal double-render probe) and asserts identical
    SHA-256 both times -- a regression guard on the builder functions
    themselves, not only on save_figure's internal mechanism."""
    for name in EXPECTED_STEMS:
        fn = getattr(figures, name)
        r1 = fn()
        r2 = fn()
        assert r1["sha256"] == r2["sha256"], (
            f"{name}: two independent calls produced different PDF bytes "
            f"({r1['sha256'][:12]} vs {r2['sha256'][:12]})"
        )


def test_every_figure_has_a_sources_sidecar():
    figures.main()
    figs_dir = PKG_DIR / "figs"
    for stem in EXPECTED_STEMS:
        sidecar = figs_dir / f"{stem}.sources.txt"
        assert sidecar.exists() and sidecar.stat().st_size > 0, (
            f"{stem}.sources.txt missing or empty -- every number on a figure must "
            f"trace to a results-file key listed here"
        )


def test_cut_and_orphaned_figures_are_not_regenerated():
    """Regression guard: none of the prior generators may reappear as a side
    effect of some future figures.py edit."""
    for name in CUT_OR_ORPHANED:
        assert not hasattr(figures, name), (
            f"{name}'s generating function has returned to figures.py -- it was cut / "
            f"found orphaned; re-adding it needs a fresh ruling, not a silent revert"
        )


def test_figure_heights_match_their_d21_budget():
    results = dict(figures.main())
    for stem, budget_cm in HEIGHT_BUDGET_CM.items():
        doc = fitz.open(results[stem]["path"])
        height_cm = doc[0].rect.height / 72.0 * 2.54
        width_cm = doc[0].rect.width / 72.0 * 2.54
        doc.close()
        assert abs(height_cm - budget_cm) < 0.01, (
            f"{stem}: height {height_cm:.3f}cm does not match its D21 budget {budget_cm}cm"
        )
        assert abs(width_cm - figstyle.LNCS_WIDTH_CM) < 0.01, (
            f"{stem}: width {width_cm:.3f}cm does not match LNCS_WIDTH_CM"
        )


def test_figures_pass_figqa_zero_in_axes_text_and_style_conformance():
    """Runs figqa's EXACT (live-Figure-object) checks -- not the weaker
    PDF-only heuristic -- against a freshly-built live figure for each stem,
    mirroring the QA loop this figure set went through before being wired in."""
    builders = {"fig_event": figures.fig_event,
                "fig_event_short": figures.fig_event_short,
                "fig_margin_paths": figures.fig_margin_paths}
    for stem, fn in builders.items():
        result = fn()
        import matplotlib.pyplot as plt
        fig = plt.gcf()
        report = figqa.run_qa(result["path"], fig=fig, height_budget_cm=HEIGHT_BUDGET_CM[stem])
        plt.close(fig)
        for check in report["checks"]:
            if check["check"] in ("in_axes_text", "style_conformance", "min_font_size",
                                    "height_budget"):
                assert check["pass"] is True, (
                    f"{stem}: figqa check {check['check']!r} failed: {check}"
                )
