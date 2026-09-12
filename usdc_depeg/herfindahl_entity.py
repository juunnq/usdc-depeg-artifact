"""Number 2 refinement, entity-resolved redemption concentration.

``herfindahl.py`` / ``results/number2_redemption_hhi.json`` ("upper_bound")
report address-level HHI over the 776 funding wallets and ASSERT it is an
upper bound on economic-entity concentration under a no-sybil condition --
"merging same-entity addresses can only concentrate volume, so address-level
HHI is conservative." That condition is never tested against data. This
module tests it directly: joins the 776 funding addresses against two
independent public label sets (dawsbot/eth-labels, brianleect/etherscan-
labels), collapses labelled addresses into entities, and recomputes HHI on
the entity partition.

Label coverage in the join is sparse, see ``labelled`` below. Read every
"no effect" finding here as *this label pair could not detect a sybil
effect*, not as no sybil effect exists.

Reuses ``herfindahl.hhi_raw`` / ``hhi_normalized`` / ``bootstrap_hhi`` for
every HHI computation so entity-level and address-level numbers are
apples-to-apples.
"""
import json
import re

import pandas as pd

import data_io
from constants import COINBASE_CONDUITS, COINBASE_HOTWALLET, DATA_DIR, RESULTS_DIR, SEED
from herfindahl import bootstrap_hhi, hhi_normalized, hhi_raw

LABELS_DIR = DATA_DIR / "n1" / "labels"
DAWSBOT_CSV = LABELS_DIR / "dawsbot_eth-labels" / "accounts.csv"
BRIANLEECT_JSON = LABELS_DIR / "brianleect_etherscan-labels" / "combinedAccountLabels.json"

# Labels whose text names a third-party exchange/custodian brand, for the
# custodian-exclusion recompute (item 5). Conservative and explicit: derived
# only from the label/category text actually observed on the 776 funding
# addresses (see EXCHANGE_CUSTODIAN_CLASSIFICATION below for the audit trail).
# "circle" / "centre" name the USDC ISSUER (Circle) / its former governing
# consortium (Centre), not a third-party exchange or custodian, so they
# are excluded from this set.
EXCHANGE_CUSTODIAN_LABELS = {"coinbase"}
ISSUER_LABELS = {"circle", "centre"}

_TRAILING_NUM_RE = re.compile(r"\s+\d+\s*$")


def _load_dawsbot_mainnet() -> dict:
    """dawsbot/eth-labels accounts.csv, filtered to chainId == 1 (Ethereum
    mainnet), lowercased, keyed by address -> list of {label, nameTag}."""
    df = pd.read_csv(DAWSBOT_CSV)
    df = df[df["chainId"] == 1].copy()
    df["address"] = df["address"].str.lower()
    out: dict = {}
    for _, row in df.iterrows():
        tag = row["nameTag"] if isinstance(row["nameTag"], str) and row["nameTag"].strip() else None
        out.setdefault(row["address"], []).append({"label": row["label"], "nameTag": tag})
    return out


def _load_brianleect() -> dict:
    """brianleect/etherscan-labels combinedAccountLabels.json, lowercased,
    keyed by address -> {name, labels}."""
    with open(BRIANLEECT_JSON, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {addr.lower(): v for addr, v in raw.items()}


def sybil_detection_power(N: int, K: int, ks: tuple = (2, 3, 10)) -> dict:
    """Exact hypergeometric probability that a k-address sybil entity, its addresses
    scattered arbitrarily among the N total funding addresses, would have been
    CAUGHT by this join: i.e. that AT LEAST 2 of its k addresses land among the K
    addresses this join actually labels (sampling WITHOUT replacement from the fixed,
    finite population of N addresses; both the entity's k addresses and the join's K
    labelled addresses are draws from the same 776-address population).

    An adversarial review cited different figures ({2: 6.6e-6, 3: 2.0e-5, 10: 2.9e-4})
    for K=2, a live recomputation confirmed those figures do NOT match this exact
    hypergeometric; they match a WITH-replacement binomial
    approximation instead (p = K/N per address, P(X>=2) = 1-(1-p)^k-k*p*(1-p)^(k-1)),
    which is the wrong sampling model here (labels and sybil-entity addresses are both
    drawn without replacement from a fixed set of 776) and overstates detection power by
    ~2x at this coverage. This function reports the exact hypergeometric; the
    discrepancy is flagged, not silently resolved in the adversary's favor, see
    resolve()'s 'sybil_detection_power_discrepancy_vs_adversarial_review' field."""
    from math import comb
    out = {}
    for k in ks:
        total = comb(N, k)
        hits = sum(comb(K, x) * comb(N - K, k - x) for x in range(2, min(k, K) + 1))
        out[k] = hits / total if total else 0.0
    return out


def normalize_entity(raw: str) -> str:
    """Collapse "<Entity> N", "<Entity>: Suffix N", "<Entity> Deposit" etc to
    bare "<Entity>". Conservative on purpose: strips only a trailing integer
    and a colon-delimited suffix, so it never merges two raw labels that
    don't share a literal prefix (no fuzzy matching, no substring merges)."""
    s = _TRAILING_NUM_RE.sub("", raw.strip())     # "Coinbase 10" -> "Coinbase"
    s = s.split(":", 1)[0].strip()                # "Coinbase: X 1" -> "Coinbase"
    s = _TRAILING_NUM_RE.sub("", s)                # strip a number stranded after the colon-split
    return s


def _wallet_raw_label(wallet: str, daws: dict, bl: dict) -> str | None:
    """One raw label string for a wallet, preferring a dawsbot nameTag, then
    its category label, then the brianleect name. Returns None if unlabelled
    in both sets."""
    if wallet in daws:
        for rec in daws[wallet]:
            if rec["nameTag"]:
                return rec["nameTag"]
        return daws[wallet][0]["label"]
    if wallet in bl:
        return bl[wallet]["name"]
    return None


def _wallet_category_labels(wallet: str, daws: dict, bl: dict) -> set:
    """Lowercase category/label slugs seen for a wallet, across both sets."""
    cats = set()
    for rec in daws.get(wallet, []):
        cats.add(str(rec["label"]).lower())
    for lab in bl.get(wallet, {}).get("labels", []):
        cats.add(str(lab).lower())
    return cats


def load_labels() -> tuple:
    """Load both label sets. Returns (dawsbot_map, brianleect_map)."""
    return _load_dawsbot_mainnet(), _load_brianleect()


def resolve() -> dict:
    """Run the full entity resolution + tests (items 1-7) and return the
    JSON-serializable result block."""
    rdf = data_io.load_redemptions().copy()
    rdf["wallet"] = rdf["wallet"].str.lower()
    assert rdf["wallet"].is_unique, "expected one row per funding wallet"
    wallets = rdf["wallet"].tolist()
    vol = rdf.set_index("wallet")["volume"]
    total_vol = float(vol.sum())
    n_wallets = len(wallets)

    daws, bl = load_labels()
    daws_hits = {w for w in wallets if w in daws}
    bl_hits = {w for w in wallets if w in bl}
    union_hits = daws_hits | bl_hits

    def _share_block(hits: set) -> dict:
        return {
            "n_labelled": len(hits),
            "address_share": len(hits) / n_wallets,
            "volume_share": float(vol.loc[list(hits)].sum() / total_vol) if hits else 0.0,
        }

    labelled = {
        "dawsbot": _share_block(daws_hits),
        "brianleect": _share_block(bl_hits),
        "union": _share_block(union_hits),
        "note": ("Label coverage of the 776 funding addresses is sparse (see counts "
                 "above) -- the volume share is high only because one of the two "
                 "largest redeemers happens to carry a direct label; every "
                 "'no sybil effect found' result below is bounded by this coverage, "
                 "not proof the true entity count is smaller."),
    }

    # --- entity normalisation (item 2) --------------------------------------
    raw_to_entity = {}
    entity_id_by_wallet = {}
    for w in union_hits:
        raw = _wallet_raw_label(w, daws, bl)
        entity = normalize_entity(raw)
        raw_to_entity[raw] = entity
        entity_id_by_wallet[w] = entity
    entity_mapping_table = [{"raw_label": r, "normalized_entity": e} for r, e in sorted(raw_to_entity.items())]

    rdf["entity_id"] = rdf["wallet"].map(lambda w: entity_id_by_wallet.get(w, w))

    # --- entity HHI (item 3) -------------------------------------------------
    entity_vol = rdf.groupby("entity_id")["volume"].sum()
    entity_hhi_raw = hhi_raw(entity_vol.values)
    entity_hhi_norm = hhi_normalized(entity_vol.values)
    entity_boot = bootstrap_hhi(entity_vol.values, seed=SEED)
    entity_block = {
        "n_entities": int(entity_vol.size),
        "n_addresses": n_wallets,
        "hhi_raw": entity_hhi_raw,
        "hhi_normalized": entity_hhi_norm,
        "effective_n_entities": 1.0 / entity_hhi_raw,
        "bootstrap": entity_boot,
    }

    # --- direct no-sybil test (item 4) ---------------------------------------
    addr_counts = rdf.groupby("entity_id").size()
    multi_addr_entities = addr_counts[addr_counts >= 2]
    sybil_share = float(entity_vol.loc[multi_addr_entities.index].sum() / total_vol) if len(multi_addr_entities) else 0.0
    address_hhi_raw = hhi_raw(vol.values)  # HHI before any merge (address-level)
    sybil_test = {
        "n_entities_with_2plus_addresses": int(len(multi_addr_entities)),
        "those_entities": {k: int(v) for k, v in multi_addr_entities.items()},
        "combined_volume_share_of_multi_address_entities": sybil_share,
        "hhi_before_merge_address_level": address_hhi_raw,
        "hhi_after_merge_entity_level": entity_hhi_raw,
        "delta": entity_hhi_raw - address_hhi_raw,
        "interpretation": (
            "No labelled entity in this join holds >=2 of the 776 funding addresses, "
            "so the merge changes nothing: entity HHI == address HHI to full "
            "precision. This does NOT confirm the no-sybil assumption -- it means "
            "the label coverage (union_hits above) is too sparse to exercise the "
            "test the manuscript needs. A denser resolution (Arkham/Nansen/MZZ) "
            "could still find multi-address entities this join cannot see."
        ),
    }

    # --- custodian-exclusion recompute (item 5) -------------------------------
    exchange_custodian_wallets = {w for w in union_hits if _wallet_category_labels(w, daws, bl) & EXCHANGE_CUSTODIAN_LABELS}
    issuer_wallets = {w for w in union_hits if _wallet_category_labels(w, daws, bl) & ISSUER_LABELS}

    def _hhi_block(sub_vol) -> dict:
        v = sub_vol.values if hasattr(sub_vol, "values") else sub_vol
        h = hhi_raw(v)
        return {
            "n_addresses": int(len(v)),
            "hhi_raw": h,
            "hhi_normalized": hhi_normalized(v),
            "largest_share": float(max(v) / sum(v)),
            "effective_n": 1.0 / h,
        }

    excl_a_df = rdf[~rdf["wallet"].isin(exchange_custodian_wallets)]
    all_custodian_excluded = _hhi_block(excl_a_df["volume"])
    all_custodian_excluded["excluded_wallets"] = sorted(exchange_custodian_wallets)
    all_custodian_excluded["classification_basis"] = {
        "exchange_custodian_labels_matched": sorted(EXCHANGE_CUSTODIAN_LABELS),
        "issuer_labels_excluded_from_custodian_class": sorted(ISSUER_LABELS),
        "note": ("Classification is by label/category text actually observed on the "
                 "776 addresses: 'coinbase' (dawsbot label) is a third-party exchange/"
                 "custodian brand. 'circle' / 'centre' name the USDC issuer and its "
                 "former governing consortium, not a third-party custodian, so those "
                 "wallets are kept in this exclusion and only removed in the separate "
                 "issuer-flagged wallet list below."),
    }
    all_custodian_excluded["issuer_labelled_wallets_not_excluded"] = sorted(issuer_wallets)

    is_coinbase_conduit = rdf["wallet"].isin([a.lower() for a in COINBASE_CONDUITS])
    coinbase_only_excluded = _hhi_block(rdf.loc[~is_coinbase_conduit, "volume"])
    coinbase_only_excluded["basis"] = (
        "Removes constants.COINBASE_CONDUITS (both conduits), matching the existing "
        "results/number2_redemption_hhi.json 'ex_custodian' figure (hhi_raw ~0.0671). "
        "This is NOT purely label-driven -- only one of the two conduits carries a "
        "direct label in either set (see item 6) -- it reproduces the paper's own "
        "on-chain Coinbase attribution for continuity/comparison with (a) above."
    )
    custodian_exclusion = {
        "all_labelled_exchange_custodian_excluded": all_custodian_excluded,
        "coinbase_conduits_excluded_existing_figure": coinbase_only_excluded,
    }

    # --- verify the paper's specific claim (item 6) ---------------------------
    conduit_a, conduit_b = [a.lower() for a in COINBASE_CONDUITS]  # (bigger, smaller) per constants.py order
    hot = COINBASE_HOTWALLET.lower()

    def _label_report(addr: str) -> dict:
        daws_recs = daws.get(addr)
        bl_rec = bl.get(addr)
        return {
            "address": addr,
            "in_776_funding_addresses": addr in vol.index,
            "share_of_volume": float(vol.get(addr, 0.0) / total_vol) if addr in vol.index else None,
            "dawsbot_mainnet": daws_recs,
            "brianleect": bl_rec,
            "labelled": bool(daws_recs or bl_rec),
        }

    claim_check = {
        "conduit_a_larger_40.94pct": _label_report(conduit_a),
        "conduit_b_smaller_28.63pct": _label_report(conduit_b),
        "coinbase_hotwallet_upstream_aggregator": _label_report(hot),
        "finding": (
            "The larger conduit (conduit_a, 40.94% of volume) IS labelled "
            "'Coinbase: Circle Deposit 1' (dawsbot, category 'coinbase') -- a direct, "
            "unambiguous label-set corroboration of the manuscript's Coinbase "
            "attribution for that address. The smaller conduit (conduit_b, 28.63% of "
            "volume) is UNLABELLED in both sets. COINBASE_HOTWALLET is not itself one "
            "of the 776 funding addresses (it is the documented upstream aggregator "
            "feeding the conduits), but where it does appear in the label data it IS "
            "tagged 'Coinbase 10' / category 'coinbase' in both sets, corroborating "
            "constants.py's identification of the hot wallet. Net: the label data "
            "corroborates the manuscript's Coinbase attribution for the hot wallet and "
            "for 40.94 of the 69.57 claimed points, but does NOT independently "
            "corroborate the remaining 28.63-point conduit -- that attribution rests "
            "on the paper's own on-chain tracing (constants.py), not on either public "
            "label set."
        ),
    }

    # --- unlabelled tail (item 7) ----------------------------------------------
    unl_df = rdf[~rdf["wallet"].isin(union_hits)]
    largest_unl_row = unl_df.loc[unl_df["volume"].idxmax()]

    # an adversarial review: the prior worst-case construction merged ONLY the unlabelled tail
    # among itself, holding conduit_a (the one externally labelled custodian) separate
    #, that is NOT the true supremum. At 2/776 coverage, nothing in either label set
    # rules out conduit_a being the SAME entity as some or all of the unlabelled tail.
    # The label-consistent supremum merges the entire unlabelled tail WITH conduit_a,
    # holding only the other independently-labelled address (the issuer wallet)
    # separate.
    other_labelled = [w for w in union_hits if w != conduit_a]
    supremum_entity_vol = float(vol.loc[conduit_a] + unl_df["volume"].sum())
    supremum_vols = [supremum_entity_vol] + list(vol.loc[other_labelled].values)
    label_consistent_supremum_hhi = hhi_raw(supremum_vols)

    unlabelled_tail = {
        "largest_unlabelled_wallet": str(largest_unl_row["wallet"]),
        "largest_unlabelled_share": float(largest_unl_row["volume"] / total_vol),
        "label_consistent_supremum_hhi": label_consistent_supremum_hhi,
        "label_consistent_supremum_assumption": (
            "An adversarial review: the ENTIRE unlabelled tail (776 - |union_hits| addresses) "
            "merges WITH the one externally labelled custodian (conduit_a, 'Coinbase: "
            "Circle Deposit 1') into a single entity -- nothing in either label set "
            "rules this out at 2/776 coverage. The other independently labelled address "
            "(the issuer wallet) is held separate. This REPLACES a prior "
            "worst_case_single_entity_hhi construction (~0.5144) that merged only the "
            "unlabelled tail among itself while holding conduit_a separate -- a weaker, "
            "inconsistent worst case. With coverage this sparse, the entity HHI is "
            "bounded only by our own attribution, not by evidence: we claim no "
            "worst-case cap."
        ),
    }

    # --- attribution split / no-sybil status / label power ---------------------------
    conduit_a_share = float(vol.loc[conduit_a] / total_vol)
    conduit_b_share = float(vol.loc[conduit_b] / total_vol)
    drop_conduit_b_only_hhi = hhi_raw(rdf.loc[rdf["wallet"] != conduit_b, "volume"].values)
    sybil_power = sybil_detection_power(n_wallets, labelled["union"]["n_labelled"])
    sybil_power_adversarial = {2: 6.6e-6, 3: 2.0e-5, 10: 2.9e-4}  # cited in an adversarial review

    return {
        "method": "Joins the 776 frozen funding addresses (data/redemptions_by_wallet.csv) "
                  "against dawsbot/eth-labels and brianleect/etherscan-labels (both lowercased for the join), "
                  "collapses labelled addresses to normalized entities, and directly tests the manuscript's "
                  "untested no-sybil assumption on address-level HHI.",
        "seed": SEED,
        "labelled": labelled,
        "entity_normalization_mapping": entity_mapping_table,
        "entity_hhi": entity_block,
        "sybil_test": sybil_test,
        "custodian_exclusion": custodian_exclusion,
        "claim_check": claim_check,
        "unlabelled_tail": unlabelled_tail,
        # The manuscript's 69.57-point concentration figure split by label evidence --
        # 40.94 points (conduit_a) are independently corroborated by an external label
        # set; the remaining 28.63 points (conduit_b) rest on the paper's own on-chain
        # tracing (constants.py), not on either public label set.
        "externally_corroborated_share": round(conduit_a_share * 100, 2),
        "own_tracing_share": round(conduit_b_share * 100, 2),
        "no_sybil_status": f"untestable with public labels (coverage {labelled['union']['n_labelled']}/{n_wallets})",
        # HHI with conduit_b (unlabelled) removed and conduit_a (labelled) still in --
        # barely moves from removing conduit_a alone (0.2528); the collapse to ~0.067
        # needs BOTH conduits excluded, and only conduit_a's exclusion is label-supported,
        # i.e. the unlabelled conduit carries the collapse, not the labelled one.
        "drop_conduit_b_only_hhi": drop_conduit_b_only_hhi,
        "sybil_detection_power": {str(k): v for k, v in sybil_power.items()},
        "sybil_detection_power_discrepancy_vs_adversarial_review": {
            "adversarial_review_figures": {str(k): v for k, v in sybil_power_adversarial.items()},
            "recomputation": {str(k): v for k, v in sybil_power.items()},
            "note": ("The adversarial review's cited figures match a WITH-replacement "
                     "binomial approximation (p = K/N per address); this module's figures "
                     "are the exact hypergeometric (sampling WITHOUT replacement from the "
                     "fixed 776-address population, the correct model here). The binomial "
                     "approximation overstates detection power by ~2x at K=2 coverage. "
                     "Reporting the exact figure, flagged rather than silently trusting "
                     "the adversarial review's arithmetic."),
        },
    }


def write_results() -> dict:
    """Append the single top-level 'entity_resolved' key to
    results/number2_redemption_hhi.json without touching any existing key."""
    path = RESULTS_DIR / "number2_redemption_hhi.json"
    with open(path, "r", encoding="utf-8") as f:
        existing = json.load(f)
    existing["entity_resolved"] = resolve()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    return existing


if __name__ == "__main__":
    # write_results() merges 'entity_resolved' into the existing
    # results/number2_redemption_hhi.json without touching any other top-level key
    # (see report.py's preservation comment near its number2() call site).
    result = write_results()
    print(json.dumps(result["entity_resolved"], indent=2))
