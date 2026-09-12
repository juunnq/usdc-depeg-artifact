"""DAI's documented USDC exposure. Reports two reporting-based ratios; does NOT
decompose DAI's de-peg into mechanical and panic components (an earlier version of
this module attempted that decomposition; it was retired under adversarial review,
see `no_decomposition` in contagion()'s return value for the reasons).

BACKGROUND: the PSM held substantial USDC on-chain through 2021-2022, but by January
2023 much had been moved to off-chain custody (Coinbase Custody ~$500M + US Treasuries
via RWA ~$1B; ~$2.4B "in the PSM" per reporting), so the documented Maker PSM-USDC-A
contracts hold ~$0 USDC on-chain at the run date and a clean on-chain USDC-backing
fraction is not available for March 2023. A contemporaneous source separately reports
the PSM's $3.1B debt ceiling as reached on the run date (see data/n1/dai_psm_2023/);
that is a statement about the ceiling, not a custody reading, and does not reconcile
with the ~$99 on-chain balance under any pass-through-toward-100% story (see the
UNRESOLVED note on DAI_REPORTED_PSM_USDC in constants.py). We freeze what IS on-chain
(PSM custody ~$0; DAI total supply, real) and report the reporting-based figure
(DAI_REPORTED_PSM_USDC) clearly labeled as such, not as an on-chain pull.

SECURITY: key from env only (shared helpers in redemptions.py), never written to a file.

    python dai_contagion.py     # freeze on-chain DAI supply + PSM(~0); print contagion
"""
import hashlib
import json
import time

import placebo
from constants import (DAI_CONTRACT, DAI_REPORTED_PSM_USDC, DAI_RUN_DATE_TS, DATA_DIR,
                       PSM_USDC_CONTRACT, PSM_USDC_JOIN, USDC_CONTRACT)
from redemptions import _get, block_by_time  # env-only key handling, V2 endpoint

BACKING_FILE = DATA_DIR / "dai_backing.json"
RUN_DATE_UTC = "2023-03-11T12:00:00Z"


def _eth_call(to: str, data: str, block: int) -> int:
    """eth_call at a historical block via Etherscan proxy; returns the uint result."""
    j = _get({"module": "proxy", "action": "eth_call", "to": to, "data": data, "tag": hex(block)})
    res = j.get("result")
    if not isinstance(res, str) or not res.startswith("0x"):
        raise RuntimeError(f"eth_call failed for {to}: {j.get('result') or j}")
    return int(res, 16)


def _usdc_balance(addr: str, block: int) -> float:
    return _eth_call(USDC_CONTRACT, "0x70a08231" + addr[2:].rjust(64, "0"), block) / 1e6


def fetch() -> dict:
    """Freeze the on-chain reality (PSM custody ~0; DAI supply real) at the run block."""
    block = block_by_time(DAI_RUN_DATE_TS, "before")
    psm_join = _usdc_balance(PSM_USDC_JOIN, block)
    psm_contract = _usdc_balance(PSM_USDC_CONTRACT, block)
    dai_supply = _eth_call(DAI_CONTRACT, "0x18160ddd", block) / 1e18  # totalSupply(), 18 dp
    rec = {
        "run_date_ts": DAI_RUN_DATE_TS, "run_date_utc": RUN_DATE_UTC, "block": block,
        "on_chain_psm_usdc_join": psm_join,
        "on_chain_psm_usdc_contract": psm_contract,
        "on_chain_psm_usdc_total": psm_join + psm_contract,
        "dai_total_supply": dai_supply,
        "on_chain_backing_clean": False,
        "on_chain_note": "PSM custody ~$0 on-chain; USDC held off-chain (Coinbase Custody + US Treasuries)",
        "reported_psm_usdc": DAI_REPORTED_PSM_USDC,
        "reported_backing_fraction": DAI_REPORTED_PSM_USDC / dai_supply,
        "reported_source": "The Block, 2023-03-11 (Wayback-captured, contemporaneous): PSM-USDC-A reached its $3.1B cap",
        "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    json.dump(rec, open(BACKING_FILE, "w"), indent=2)
    _freeze_manifest(rec)
    print(f"on-chain PSM USDC ~${rec['on_chain_psm_usdc_total']:.0f} (off-chain custody); "
          f"DAI supply ${dai_supply/1e9:.3f}B; reported backing "
          f"{rec['reported_backing_fraction']*100:.1f}% (contemporaneous reporting)")
    return rec


def refreeze_reported(psm_usdc: float, source: str,
                      source_collateral_share: float | None = None) -> dict:
    """Update ONLY the reporting-based PSM-USDC figure in the already-frozen dai_backing.json,
    leaving the on-chain fields (block, dai_total_supply, on-chain PSM custody) untouched --
    those are deterministic historical eth_call results already correctly frozen at a fixed
    historical block, so re-verifying them needs no fresh ETHERSCAN_API_KEY call. Use this
    when a better contemporaneous reporting source is found and the key is unavailable.
        python -c "import dai_contagion as dc; dc.refreeze_reported(3.1e9, 'source string')"
    """
    if not BACKING_FILE.exists():
        raise RuntimeError(
            "data/dai_backing.json missing -- run fetch() first (needs ETHERSCAN_API_KEY)")
    rec = json.load(open(BACKING_FILE))
    rec["reported_psm_usdc"] = psm_usdc
    rec["reported_backing_fraction"] = psm_usdc / rec["dai_total_supply"]
    rec["reported_source"] = source
    if source_collateral_share is not None:
        # The SAME source also states a USDC share of DAI's total collateral, on a
        # different denominator. Frozen alongside so the two ratios can be reported
        # together; the paper selects neither as a pass-through coefficient.
        rec["source_collateral_share"] = source_collateral_share
    rec["retrieved_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(rec, open(BACKING_FILE, "w"), indent=2)
    _freeze_manifest(rec)
    print(f"reported PSM USDC -> ${psm_usdc/1e9:.2f}B; reported backing "
          f"{rec['reported_backing_fraction']*100:.1f}% ({source})")
    return rec


def _freeze_manifest(rec: dict):
    mpath = DATA_DIR / "MANIFEST.json"
    man = json.load(open(mpath)) if mpath.exists() else {"sources": [], "files": {}}
    man.setdefault("sources", [])
    man.setdefault("files", {})
    man["sources"] = [s for s in man["sources"] if s.get("file") != "dai_backing.json"]
    man["sources"].append({
        "file": "dai_backing.json",
        "source": "Etherscan eth_call (apikey from env, redacted): USDC.balanceOf(PSM-USDC-A) + DAI.totalSupply()",
        "block": rec["block"], "run_date_utc": RUN_DATE_UTC,
        "on_chain_psm_usdc_total": rec["on_chain_psm_usdc_total"],
        "on_chain_backing_clean": False,
        "reported_psm_usdc": rec["reported_psm_usdc"],
        "reported_source": rec["reported_source"],
        "retrieved_utc": rec["retrieved_utc"],
    })
    man["files"]["dai_backing.json"] = {
        "sha256": hashlib.sha256(BACKING_FILE.read_bytes()).hexdigest(),
        "bytes": BACKING_FILE.stat().st_size,
    }
    json.dump(man, open(mpath, "w"), indent=2)


def contagion() -> dict:
    """Mechanical USDC pass-through vs observed DAI de-peg (offline; reads frozen data).
    De-peg magnitudes come from the frozen price snapshot (placebo), single-source."""
    if not BACKING_FILE.exists():
        return {"status": "PENDING_DATA",
                "reason": "data/dai_backing.json missing -- run `python dai_contagion.py` with ETHERSCAN_API_KEY set."}
    d = json.load(open(BACKING_FILE))
    p = placebo.placebo()
    usdc_bps = p["USDC"]["max_depeg_bps"]
    dai_bps = p["DAI"]["max_depeg_bps"]
    psm_share = d["reported_backing_fraction"]
    collateral_share = d.get("source_collateral_share")
    return {
        "status": "OK_REPORTED_EXPOSURE",  # exposure reported; NO decomposition claimed
        "on_chain_backing_clean": False,
        "on_chain_psm_usdc_total": d["on_chain_psm_usdc_total"],
        "dai_total_supply_usd": d["dai_total_supply"],
        "reported_psm_usdc": d["reported_psm_usdc"],
        "psm_share_of_dai_supply": psm_share,
        "source_collateral_share": collateral_share,
        "reported_source": d["reported_source"],
        "block": d["block"], "run_date_utc": d["run_date_utc"],
        "usdc_depeg_bps": usdc_bps,
        "observed_dai_depeg_bps": dai_bps,
        # Illustrative only, what a pass-through would be under each of the two
        # ratios the single source gives. NOT a decomposition: see `no_decomposition`.
        "pass_through_if_psm_share_bps": psm_share * usdc_bps,
        "pass_through_if_collateral_share_bps": (
            collateral_share * usdc_bps if collateral_share is not None else None
        ),
        "no_decomposition": (
            "No mechanical/panic split is reported. The source gives two ratios with "
            "different denominators (PSM-USDC over DAI supply; USDC over total collateral) "
            "that imply pass-throughs straddling the observed de-peg, so any residual would "
            "be an artifact of the choice of ratio. The USDC->DAI mint leg was capped out at "
            "the moment analysed -- the leg whose arbitrage would pull DAI toward USDC -- so "
            "the PSM cannot be argued to drive effective pass-through toward 100%; at a "
            "pass-through of 1.0 the implied residual is negative, which the prior "
            "[0, excess] band could not represent. The on-chain PSM balance at the run-date "
            "block reads ~$99, attributed to off-chain custody but not corroborable on-chain, "
            "so the reported figure remains a debt-ceiling report, not a custody reading."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(fetch(), indent=2))
    print(json.dumps(contagion(), indent=2))
