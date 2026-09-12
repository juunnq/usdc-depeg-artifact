"""Number 2 — redemption Herfindahl estimator (raw, normalized, top-k, bootstrap)."""
import json

import pytest

import herfindahl as hh


def test_hhi_known_values():
    assert hh.hhi_raw([1, 1]) == pytest.approx(0.5)
    assert hh.hhi_raw([1, 1, 1, 1]) == pytest.approx(0.25)
    assert hh.hhi_raw([5]) == pytest.approx(1.0)
    assert hh.hhi_raw([3, 1]) == pytest.approx(0.75 ** 2 + 0.25 ** 2)


def test_hhi_ignores_zeros():
    assert hh.hhi_raw([1, 1, 0, 0]) == pytest.approx(0.5)


def test_normalized_bounds():
    assert hh.hhi_normalized([1, 1, 1, 1]) == pytest.approx(0.0, abs=1e-12)  # perfectly even
    assert hh.hhi_normalized([10]) == pytest.approx(1.0)                     # single wallet
    assert hh.hhi_normalized([97, 1, 1, 1]) > hh.hhi_normalized([25, 25, 25, 25])


def test_top_k_share():
    vols = [50, 30, 10, 5, 5]
    assert hh.top_k_share(vols, 2) == pytest.approx(0.8)
    assert hh.top_k_share(vols, 10) == pytest.approx(1.0)  # k exceeds N -> all


def test_bootstrap_is_seeded_and_brackets_point():
    vols = [100, 50, 30, 20, 10, 5, 5, 3, 2, 1]
    a = hh.bootstrap_hhi(vols, n_boot=2000, seed=20230311)
    b = hh.bootstrap_hhi(vols, n_boot=2000, seed=20230311)
    assert (a["hhi"], a["lo"], a["hi"]) == (b["hhi"], b["lo"], b["hi"])  # deterministic
    assert a["lo"] <= a["hhi"] <= a["hi"]


def test_empty_raises():
    with pytest.raises(ValueError):
        hh.hhi_raw([0, 0])


# --- frozen-snapshot gating (S5): pin the paper's concentration table ------------
def test_frozen_snapshot_hhi_pinned():
    """The paper's Table (tab:hhi) values must be pinned to the frozen redemptions
    CSV, this test fails if data/redemptions_by_wallet.csv or the attribution
    logic changes while the suite stays green."""
    import data_io
    from constants import COINBASE_CONDUITS

    df = data_io.load_redemptions()
    df = df.copy()
    df["wallet"] = df["wallet"].str.lower()
    vols = df["volume"].values
    assert len(vols) == 776                                       # N redeemers
    assert hh.hhi_raw(vols) == pytest.approx(0.2558, abs=1e-3)     # raw HHI
    assert hh.hhi_normalized(vols) == pytest.approx(0.2548, abs=1e-3)
    is_cb = df["wallet"].isin([a.lower() for a in COINBASE_CONDUITS])
    cb_share = float(df.loc[is_cb, "volume"].sum() / vols.sum())
    assert cb_share == pytest.approx(0.6957, abs=1e-3)             # Coinbase share
    vols_ex = df.loc[~is_cb, "volume"].values
    assert hh.hhi_raw(vols_ex) == pytest.approx(0.0671, abs=1e-3)  # ex-custodian


# --- FC27 must-fix: pin the seven tab:hhi statistics no test previously covered ---
def test_tabhhi_seven_unpinned_statistics_match_manuscript():
    """test_frozen_snapshot_hhi_pinned above (S5) recomputes N/HHI-raw/HHI-normalized/
    ex-custodian-HHI-raw from the CSV. Seven further statistics fc27.tex's tab:hhi
    prints had no pinning test at all: top-10 share, largest share, effective #
    redeemers, both bootstrap-CI ends, coverage of gross burns, and the ex-custodian
    largest share + effective # redeemers. Reads the persisted
    results/number2_redemption_hhi.json (report.py's output, tab:hhi's cited source
    per its caption) and asserts each to the precision the table prints."""
    from constants import RESULTS_DIR

    path = RESULTS_DIR / "number2_redemption_hhi.json"
    assert path.exists(), "run report.py: results/number2_redemption_hhi.json is a required artifact"
    n2 = json.load(open(path))
    ub, ex, cov = n2["upper_bound"], n2["ex_custodian"], n2["coverage"]

    assert round(cov["coverage_pct"], 1) == pytest.approx(89.8)            # Coverage of gross burns
    assert round(ub["top10_share"] * 100, 1) == pytest.approx(88.1)        # Top-10 share
    assert round(ub["largest_share"] * 100, 1) == pytest.approx(40.9)      # Largest share
    assert round(ub["effective_n"], 1) == pytest.approx(3.9)               # Effective # redeemers
    assert round(ub["bootstrap"]["lo"], 3) == pytest.approx(0.052)         # Bootstrap 95% CI, low
    assert round(ub["bootstrap"]["hi"], 3) == pytest.approx(0.418)         # Bootstrap 95% CI, high
    assert round(ex["largest_share"] * 100, 1) == pytest.approx(16.8)      # Largest share, ex-custodian
    assert round(ex["effective_n"], 1) == pytest.approx(14.9)              # Effective # redeemers, ex-custodian
