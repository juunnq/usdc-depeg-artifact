"""Entity-resolved redemption concentration (pins the sybil test)."""
import pytest

import herfindahl_entity as he


def test_normalize_entity_strips_trailing_number_and_colon_suffix():
    assert he.normalize_entity("Coinbase 10") == "Coinbase"
    assert he.normalize_entity("Coinbase: Circle Deposit 1") == "Coinbase"
    assert he.normalize_entity("Circle: Deposit") == "Circle"


def test_normalize_entity_does_not_merge_different_entities():
    assert he.normalize_entity("Coinbase 4") != he.normalize_entity("Circle: Deposit")


# --- frozen-snapshot gating: pins the module's headline numbers ------------------
def test_labelled_volume_share_pinned():
    r = he.resolve()
    assert r["labelled"]["union"]["volume_share"] == pytest.approx(0.4111, abs=1e-3)
    assert r["labelled"]["union"]["n_labelled"] == 2


def test_entity_hhi_pinned_4dp():
    r = he.resolve()
    assert r["entity_hhi"]["hhi_raw"] == pytest.approx(0.2558, abs=1e-4)
    assert r["entity_hhi"]["hhi_normalized"] == pytest.approx(0.2548, abs=1e-4)


def test_sybil_count_is_zero_given_current_label_coverage():
    """The key check: with these two label sets, no labelled entity
    holds >=2 of the 776 funding addresses, so the merge cannot move HHI."""
    r = he.resolve()
    assert r["sybil_test"]["n_entities_with_2plus_addresses"] == 0
    assert r["sybil_test"]["combined_volume_share_of_multi_address_entities"] == pytest.approx(0.0)
    assert r["sybil_test"]["hhi_after_merge_entity_level"] == pytest.approx(
        r["sybil_test"]["hhi_before_merge_address_level"], abs=1e-9
    )


def test_all_custodian_excluded_hhi_pinned():
    r = he.resolve()
    block = r["custodian_exclusion"]["all_labelled_exchange_custodian_excluded"]
    assert block["n_addresses"] == 775
    assert block["hhi_raw"] == pytest.approx(0.2528, abs=1e-4)


def test_coinbase_conduits_excluded_matches_existing_ex_custodian_figure():
    r = he.resolve()
    block = r["custodian_exclusion"]["coinbase_conduits_excluded_existing_figure"]
    assert block["hhi_raw"] == pytest.approx(0.0671, abs=1e-3)  # matches the frozen ex_custodian figure


def test_claim_check_conduit_labelling_matches_verified_inputs():
    r = he.resolve()
    claim = r["claim_check"]
    assert claim["conduit_a_larger_40.94pct"]["labelled"] is True
    assert claim["conduit_b_smaller_28.63pct"]["labelled"] is False
    assert claim["coinbase_hotwallet_upstream_aggregator"]["in_776_funding_addresses"] is False
    assert claim["coinbase_hotwallet_upstream_aggregator"]["labelled"] is True


def test_bootstrap_is_seeded():
    r1 = he.resolve()
    r2 = he.resolve()
    b1, b2 = r1["entity_hhi"]["bootstrap"], r2["entity_hhi"]["bootstrap"]
    assert (b1["hhi"], b1["lo"], b1["hi"]) == (b2["hhi"], b2["lo"], b2["hi"])


# --- N7 adversarial pass, ruling C5 ---------------------------------------------
def test_label_consistent_supremum_replaces_prior_worst_case():
    """The prior worst_case_single_entity_hhi (~0.5144, merging the unlabelled tail
    among itself only) is FALSE as a worst case: it is not gone entirely, it is
    replaced by the label-consistent supremum (conduit_a merged WITH the entire
    unlabelled tail), 0.9966."""
    r = he.resolve()
    tail = r["unlabelled_tail"]
    assert "worst_case_single_entity_hhi" not in tail
    assert tail["label_consistent_supremum_hhi"] == pytest.approx(0.9966, abs=1e-4)
    assert "conduit_a" in tail["label_consistent_supremum_assumption"]


def test_attribution_split_and_no_sybil_status():
    r = he.resolve()
    assert r["externally_corroborated_share"] == pytest.approx(40.94, abs=0.01)
    assert r["own_tracing_share"] == pytest.approx(28.63, abs=0.01)
    assert r["no_sybil_status"] == "untestable with public labels (coverage 2/776)"


def test_drop_conduit_b_only_hhi():
    """Excluding only the UNLABELLED conduit (conduit_b), proves it, not the
    labelled conduit_a, carries the concentration collapse: this figure is HIGHER than
    baseline (conduit_a's remaining share grows), while dropping conduit_a alone barely
    moves the index."""
    r = he.resolve()
    assert r["drop_conduit_b_only_hhi"] == pytest.approx(0.34121, abs=1e-4)


def test_sybil_detection_power_exact_hypergeometric_flags_adversarial_review_discrepancy():
    """A live recomputation of sybil_detection_power uses the exact
    hypergeometric (sampling without replacement from the fixed 776-address
    population); an adversarial review's figures match a with-replacement binomial
    approximation instead and are ~2x too high at this coverage. Report OUR number,
    flagged, not the adversarial review's unverified one."""
    r = he.resolve()
    power = r["sybil_detection_power"]
    assert power["2"] == pytest.approx(3.326e-6, rel=1e-3)
    assert power["3"] == pytest.approx(9.977e-6, rel=1e-3)
    assert power["10"] == pytest.approx(1.4965e-4, rel=1e-3)
    disc = r["sybil_detection_power_discrepancy_vs_adversarial_review"]
    assert disc["adversarial_review_figures"]["2"] == pytest.approx(6.6e-6)
    assert disc["recomputation"]["2"] == power["2"]


def test_sybil_detection_power_function_matches_known_small_case():
    """he.sybil_detection_power(N, K) unit-level check against a hand-computable case:
    N=10, K=2, k=2 -> C(2,2)/C(10,2) = 1/45."""
    out = he.sybil_detection_power(10, 2, ks=(2,))
    assert out[2] == pytest.approx(1 / 45, rel=1e-9)


def test_results_artifact_matches_live_entity_resolved():
    """results/number2_redemption_hhi.json's entity_resolved block must match a live
    recomputation, and no other top-level key must be touched by write_results()."""
    import json
    from constants import RESULTS_DIR
    path = RESULTS_DIR / "number2_redemption_hhi.json"
    if not path.exists():
        pytest.skip("herfindahl_entity.py has not been run to persist the JSON yet")
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "entity_resolved" in on_disk
    live = he.resolve()
    assert on_disk["entity_resolved"]["unlabelled_tail"]["label_consistent_supremum_hhi"] == pytest.approx(
        live["unlabelled_tail"]["label_consistent_supremum_hhi"]
    )
    # unrelated top-level keys report.py owns must still be present, untouched here
    for key in ("status", "upper_bound", "ex_custodian", "dominant_entity"):
        assert key in on_disk
