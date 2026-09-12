"""Number 4 - DAI's documented USDC exposure (offline; reads frozen dai_backing.json).

An adversarial pass retired the previous mechanical/panic decomposition: the single
contemporaneous source gives two ratios on different denominators (PSM-USDC over DAI
supply, 74%; USDC over total collateral, 36%) whose implied pass-throughs straddle the
observed de-peg, so the residual was an artifact of the ratio chosen rather than a
measurement. These tests now pin the EXPOSURE figures and, critically, guard against the
decomposition being reintroduced without a fresh ruling.
"""
import pytest

import dai_contagion as dc


def test_contagion_status_and_exposure_arithmetic():
    r = dc.contagion()
    # A reproducer missing this frozen input must see the suite go RED, not silently
    # skip past Number 4 to a green exit.
    assert r.get("status") != "PENDING_DATA", (
        f"required input missing -- {r.get('reason')}")
    assert r["status"] == "OK_REPORTED_EXPOSURE"
    assert r["on_chain_backing_clean"] is False  # USDC custody is off-chain

    # The two ratios are reported, both traceable to the same frozen source.
    assert r["psm_share_of_dai_supply"] == pytest.approx(
        r["reported_psm_usdc"] / r["dai_total_supply_usd"])
    assert 0 < r["source_collateral_share"] < r["psm_share_of_dai_supply"], (
        "the collateral-share ratio must be the smaller of the two -- if it is not, the "
        "denominators have been confused")

    # The illustrative pass-throughs are exactly ratio x USDC de-peg, nothing more.
    assert r["pass_through_if_psm_share_bps"] == pytest.approx(
        r["psm_share_of_dai_supply"] * r["usdc_depeg_bps"])
    assert r["pass_through_if_collateral_share_bps"] == pytest.approx(
        r["source_collateral_share"] * r["usdc_depeg_bps"])


def test_no_decomposition_is_reported():
    """Regression guard. The mechanical/panic split was retired by an adversarial pass;
    re-adding it needs a fresh ruling, not a silent revert. The specific defect: the two
    source ratios straddle the observed de-peg, and at a pass-through of 1.0, which the
    retired prose argued the PSM pushed toward, the implied residual is NEGATIVE, which
    the old [0, excess] band could not represent."""
    r = dc.contagion()
    for retired in ("mechanical_collateral_only_bps", "excess_panic_upper_bound_bps",
                    "dai_panic_band_bps", "reported_backing_fraction"):
        assert retired not in r, (
            f"{retired} has returned to contagion() -- the DAI decomposition was retired "
            f"under an adversarial ruling; reinstating it needs a fresh ruling")
    assert "no_decomposition" in r

    # The straddle that killed the decomposition, asserted directly so it stays true.
    lo = r["pass_through_if_collateral_share_bps"]
    hi = r["pass_through_if_psm_share_bps"]
    observed = r["observed_dai_depeg_bps"]
    assert lo < observed, "collateral-share pass-through should sit below the observed de-peg"
    assert hi < observed, "PSM-share pass-through should sit below the observed de-peg"
    assert r["usdc_depeg_bps"] > observed, (
        "at a pass-through of 1.0 the mechanical component exceeds the observed DAI de-peg, "
        "so the retired residual would be negative -- this is the arithmetic that killed it")


# --- frozen-snapshot gating: pin the exposure figures the paper prints ----------
def test_frozen_dai_exposure_pinned():
    """Pin tab:dai's printed figures: 1233/1141 bps, $4.19B supply, $3.1B reported cap,
    74% of DAI supply, 36% of collateral, ~$99 on-chain."""
    r = dc.contagion()
    assert r["usdc_depeg_bps"] == pytest.approx(1233.3, abs=0.5)
    assert r["observed_dai_depeg_bps"] == pytest.approx(1140.6, abs=0.5)
    assert r["dai_total_supply_usd"] == pytest.approx(4.194e9, rel=1e-3)
    assert r["reported_psm_usdc"] == pytest.approx(3.1e9, rel=1e-6)
    assert r["psm_share_of_dai_supply"] == pytest.approx(0.7392, abs=1e-3)
    assert r["source_collateral_share"] == pytest.approx(0.36, abs=1e-6)
    assert r["on_chain_psm_usdc_total"] == pytest.approx(99.33, abs=0.5)
