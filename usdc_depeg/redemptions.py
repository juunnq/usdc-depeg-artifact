"""Number 2 data — redeemer-level USDC redemption concentration over the frozen
window, via Etherscan, by FIFO burn-attribution.

SECURITY: the API key is read from ETHERSCAN_API_KEY in the environment ONLY. It is
never written to any file (CSV, MANIFEST) or printed; manifest entries are stored
key-redacted.

Why burn-attribution (not raw inflow-to-minter): Circle's minter is a busy treasury
-- over the window it received ~$9.06B from external senders AND ~$2.35B in fresh
mints, while burning ~$8.13B and forwarding ~$3.41B back out. Raw inflow therefore
over-counts redemptions (coverage > 100%). We instead FIFO-match the ACTUAL burns to
the external deposits that funded them: every counted dollar is a real burn,
mint-funded burns and non-redemption pass-through are excluded, and coverage is
<= 100% of gross burns.

Method:
  1. Burns: USDC `Transfer -> 0x0`; their `from` addresses are Circle's burner set M
     (on-chain ground truth). The dominant minter (~99.8% of burns) is the pipeline.
  2. Pull ALL inflows to / outflows from the minter, time-ordered (block, logIndex).
  3. FIFO: inflows add lots (external deposit, or mint when from == 0x0); a burn
     consumes lots front-first and attributes consumed EXTERNAL value to that sender;
     a non-burn outflow consumes lots WITHOUT attributing (forwarded, not redeemed).
     Per-sender burned value = that sender's redemption.

Caveats (mirrored in README): the burner set is derived from burns, not a tagged
list; exchange/intermediary senders aggregate many ultimate redeemers (so the HHI is
an upper bound); FIFO is a conventional matching of fungible balances; off-chain
redemptions are unobserved.

    python redemptions.py --burns-only    # cheap probe: M + gross burned + supply
    python redemptions.py                 # full: live FIFO burn-attribution -> CSV + MANIFEST
    python redemptions.py --from-frozen   # offline: re-validate the already-frozen CSV
                                           # (thin re-validation, NOT a live re-attribution --
                                           # the raw per-event Etherscan log is not frozen,
                                           # only this CSV's output is)
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict, deque

import pandas as pd
import requests

import herfindahl as hh
from constants import DATA_DIR, USDC_CONTRACT, WINDOW_END_S, WINDOW_START_S, ZERO_ADDRESS

API = "https://api.etherscan.io/v2/api"  # V2 multichain endpoint (chainid required)
CHAIN_ID = 1  # Ethereum mainnet
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TIMEOUT = 60
SLEEP = 0.22  # ~4.5 req/s, under the free-tier 5/s cap
REDEMPTIONS_FILE = DATA_DIR / "redemptions_by_wallet.csv"


class FrozenFileError(RuntimeError):
    """Raised when the live-fetch path is asked to overwrite an already-frozen,
    MANIFEST-listed file. Frozen files are read-only, use --from-frozen instead."""


def _key() -> str:
    k = os.environ.get("ETHERSCAN_API_KEY")
    if not k:
        raise RuntimeError("ETHERSCAN_API_KEY not set in environment.")
    return k


def _pad(addr: str) -> str:
    return "0x" + addr[2:].lower().rjust(64, "0")


def _addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def _get(params: dict) -> dict:
    p = dict(params)
    p["chainid"] = CHAIN_ID
    p["apikey"] = _key()
    j = {}
    for attempt in range(5):
        r = requests.get(API, params=p, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        res = j.get("result")
        if isinstance(res, str) and "rate limit" in res.lower():
            time.sleep(1.0 + attempt)
            continue
        break
    time.sleep(SLEEP)
    return j


def block_by_time(ts: int, closest: str) -> int:
    j = _get({"module": "block", "action": "getblocknobytime",
              "timestamp": ts, "closest": closest})
    if j.get("status") != "1":
        raise RuntimeError(f"block lookup failed: {j.get('result')}")
    return int(j["result"])


def transfer_logs(lo: int, hi: int, topic1: str = None, topic2: str = None,
                  max_calls: int = 8000):
    """USDC Transfer logs filtered by topic1 (from) and/or topic2 (to) in [lo, hi].
    Adaptive block-range splitting beats the 1000-log/call cap. Returns (logs, truncated)."""
    out, stack, calls, truncated = [], [(lo, hi)], 0, False
    while stack:
        if calls >= max_calls:
            truncated = True
            break
        a, b = stack.pop()
        calls += 1
        p = {"module": "logs", "action": "getLogs", "address": USDC_CONTRACT,
             "fromBlock": a, "toBlock": b, "topic0": TRANSFER_TOPIC, "page": 1, "offset": 1000}
        if topic1:
            p["topic1"] = topic1
            p["topic0_1_opr"] = "and"
        if topic2:
            p["topic2"] = topic2
            p["topic0_2_opr"] = "and"
        if topic1 and topic2:
            p["topic1_2_opr"] = "and"
        j = _get(p)
        res = j.get("result")
        if j.get("status") == "1" and isinstance(res, list):
            if len(res) >= 1000 and a < b:
                mid = (a + b) // 2
                stack.append((a, mid))
                stack.append((mid + 1, b))
            else:
                out.extend(res)
        else:
            if "No records found" in (j.get("message") or "") or res in ([], None):
                continue
            if a < b:
                mid = (a + b) // 2
                stack.append((a, mid))
                stack.append((mid + 1, b))
    return out, truncated


def _supply_decline():
    """(start, min, decline) USDC circulating from the frozen snapshot, or Nones."""
    path = DATA_DIR / "usdc_supply_daily.csv"
    if not path.exists():
        return None, None, None
    sup = pd.read_csv(path).dropna()
    if sup.empty:
        return None, None, None
    start = float(sup.iloc[0]["circulating_usd"])
    lo = float(sup["circulating_usd"].min())
    return start, lo, start - lo


def _refuse_if_manifested() -> None:
    """Guard for the live-fetch path: refuse before any network call if
    redemptions_by_wallet.csv is already listed in MANIFEST.json's files{}.
    Frozen files are read-only in this project, use --from-frozen to
    re-validate the existing snapshot instead of re-attributing it."""
    mpath = DATA_DIR / "MANIFEST.json"
    existing_files = json.load(open(mpath)).get("files", {}) if mpath.exists() else {}
    if REDEMPTIONS_FILE.name in existing_files:
        raise FrozenFileError(
            f"refusing to overwrite '{REDEMPTIONS_FILE.name}': already frozen and "
            f"listed in MANIFEST.json files{{}}. Frozen files are read-only -- run "
            f"`python redemptions.py --from-frozen` to re-validate it instead."
        )


def from_frozen() -> dict:
    """Offline re-validation (--from-frozen): reads the already-frozen
    redemptions_by_wallet.csv and re-emits the same summary statistics the live
    path prints, cross-checked against the MANIFEST.json entry recorded when the
    live FIFO attribution last ran (sha256 + n_redeemers). NOT a live
    re-attribution: the raw per-event Etherscan log is not frozen, only this
    CSV's output is (R3), so this mode can only re-validate what was already
    computed, not reproduce it from source events. No network access, no
    ETHERSCAN_API_KEY required."""
    if not REDEMPTIONS_FILE.exists():
        raise FileNotFoundError(
            f"{REDEMPTIONS_FILE} not found -- --from-frozen re-validates the "
            "already-frozen attribution output, it cannot produce it from scratch. "
            "Run `python redemptions.py` (needs ETHERSCAN_API_KEY) to attribute "
            "from source, or restore the frozen CSV."
        )
    df = pd.read_csv(REDEMPTIONS_FILE)
    vols = df["volume"].values
    n = len(vols)
    total = float(vols.sum())

    mpath = DATA_DIR / "MANIFEST.json"
    man = json.load(open(mpath)) if mpath.exists() else {}
    src = next((s for s in man.get("sources", [])
               if s.get("file") == "redemptions_by_wallet.csv"), {})
    recorded_sha = man.get("files", {}).get("redemptions_by_wallet.csv", {}).get("sha256")
    actual_sha = hashlib.sha256(REDEMPTIONS_FILE.read_bytes()).hexdigest()

    mismatches = []
    if recorded_sha and actual_sha != recorded_sha:
        mismatches.append(f"sha256 mismatch: MANIFEST records {recorded_sha}, file is {actual_sha}")
    if src.get("n_redeemers") is not None and src["n_redeemers"] != n:
        mismatches.append(f"n_redeemers mismatch: MANIFEST records {src['n_redeemers']}, CSV has {n}")
    if mismatches:
        raise RuntimeError("redemptions.py --from-frozen: frozen CSV disagrees with "
                           "MANIFEST.json -- " + "; ".join(mismatches))

    cov_pct = src.get("coverage_pct")
    print("=== Redemptions (--from-frozen: offline re-validation of the frozen attribution) ===")
    print(f"redeemers: {n}   attributed: ${total/1e9:.3f}B   "
          f"coverage {cov_pct:.1f}% of gross burns (recorded)" if cov_pct is not None
          else f"redeemers: {n}   attributed: ${total/1e9:.3f}B   coverage: n/a")
    print(f"HHI raw {hh.hhi_raw(vols):.4f}   normalized {hh.hhi_normalized(vols):.4f}   "
          f"top-10 {hh.top_k_share(vols,10)*100:.1f}%   largest {vols.max()/total*100:.1f}%")
    print("MANIFEST cross-check: OK (sha256 + n_redeemers match recorded values).")
    return {"n_redeemers": n, "attributed_usd": total, "coverage_pct": cov_pct,
            "hhi_raw": hh.hhi_raw(vols), "sha256_ok": True}


def fetch_burns(lo, hi):
    """Burns (Transfer -> 0x0); `from` addresses are Circle's burner set M."""
    logs, trunc = transfer_logs(lo, hi, topic2=_pad(ZERO_ADDRESS))
    burn_by, gross = {}, 0.0
    for l in logs:
        f = _addr(l["topics"][1])
        v = int(l["data"], 16) / 1e6
        burn_by[f] = burn_by.get(f, 0.0) + v
        gross += v
    return burn_by, gross, len(logs), trunc


def fifo_attribute(minter, lo, hi):
    """FIFO-match the minter's burns to the external deposits that funded them.
    Returns (attributed: sender->$, stats, truncated)."""
    mp = _pad(minter)
    inflows, t1 = transfer_logs(lo, hi, topic2=mp)   # to = minter
    outflows, t2 = transfer_logs(lo, hi, topic1=mp)  # from = minter

    def k(l):
        return (int(l["blockNumber"], 16), int(l["logIndex"], 16))

    events = [(k(l), "IN", _addr(l["topics"][1]), int(l["data"], 16) / 1e6) for l in inflows]
    for l in outflows:
        t = _addr(l["topics"][2])
        events.append((k(l), "BURN" if t == ZERO_ADDRESS else "OUT", t, int(l["data"], 16) / 1e6))
    events.sort(key=lambda e: e[0])

    q = deque()                      # FIFO lots: [sender, remaining]
    attributed = defaultdict(float)
    stats = {"ext_in": 0.0, "mint_in": 0.0, "burns": 0.0, "nonburn_out": 0.0, "unbacked": 0.0}

    def consume(amount, is_burn):
        while amount > 1e-9 and q:
            lot = q[0]
            take = min(amount, lot[1])
            lot[1] -= take
            amount -= take
            if is_burn and lot[0] != ZERO_ADDRESS:  # burn funded by an external deposit
                attributed[lot[0]] += take
            if lot[1] <= 1e-9:
                q.popleft()
        if amount > 1e-9 and is_burn:
            stats["unbacked"] += amount  # burn drew on pre-window balance

    for _, kind, addr, v in events:
        if kind == "IN":
            stats["mint_in" if addr == ZERO_ADDRESS else "ext_in"] += v
            q.append([addr, v])
        elif kind == "BURN":
            stats["burns"] += v
            consume(v, True)
        else:
            stats["nonburn_out"] += v
            consume(v, False)
    return attributed, stats, (t1 or t2)


def main():
    ap = argparse.ArgumentParser(description="FIFO burn-attribution of USDC redemptions")
    ap.add_argument("--burns-only", action="store_true", help="cheap probe: M + gross burns + supply")
    ap.add_argument("--from-frozen", action="store_true",
                    help="offline: re-validate the already-frozen redemptions_by_wallet.csv "
                         "against MANIFEST.json (sha256 + n_redeemers) and re-print its "
                         "summary. No network, no ETHERSCAN_API_KEY. This is a THIN "
                         "RE-VALIDATION of the frozen output, not a live re-attribution -- "
                         "the raw per-event Etherscan log is not frozen, only this CSV is.")
    args = ap.parse_args()

    if args.from_frozen:
        from_frozen()
        return

    if not args.burns_only:
        _refuse_if_manifested()  # burns-only never writes the CSV; nothing to guard

    lo = block_by_time(WINDOW_START_S, "after")
    hi = block_by_time(WINDOW_END_S, "before")
    start, smin, decline = _supply_decline()

    burn_by, gross, n_burns, tb = fetch_burns(lo, hi)
    M = sorted(burn_by, key=burn_by.get, reverse=True)
    minter = M[0]

    print("=== Burns (Circle burner/minter set M) ===")
    print(f"blocks {lo}..{hi}   burn events: {n_burns}   gross burned: ${gross/1e9:.3f}B   truncated={tb}")
    for m in M[:6]:
        print(f"  {m}   ${burn_by[m]/1e9:.3f}B")
    if decline:
        print(f"on-chain supply (start->min): ${start/1e9:.2f}B -> ${smin/1e9:.2f}B (-${decline/1e9:.2f}B)")
    if args.burns_only:
        return

    attributed, stats, trunc = fifo_attribute(minter, lo, hi)
    attr_total = sum(attributed.values())
    coverage = attr_total / gross if gross else float("nan")
    vols = sorted(attributed.values(), reverse=True)
    n = len(vols)

    df = pd.DataFrame(sorted(attributed.items(), key=lambda kv: kv[1], reverse=True),
                      columns=["wallet", "volume"])
    out_csv = REDEMPTIONS_FILE
    df.to_csv(out_csv, index=False)

    print("\n=== Minter flow reconciliation (dominant minter) ===")
    print(f"ext_in ${stats['ext_in']/1e9:.3f}B   mint_in ${stats['mint_in']/1e9:.3f}B   "
          f"burns ${stats['burns']/1e9:.3f}B   nonburn_out ${stats['nonburn_out']/1e9:.3f}B")
    print(f"balance change ~ ${(stats['ext_in']+stats['mint_in']-stats['burns']-stats['nonburn_out'])/1e9:.3f}B   "
          f"burns on pre-window balance ~ ${stats['unbacked']/1e9:.3f}B")
    print("\n=== Redemptions (FIFO burn-attributed to external senders) ===")
    print(f"redeemers: {n}   attributed: ${attr_total/1e9:.3f}B   coverage {coverage*100:.1f}% of gross burns   truncated={trunc}")
    if n:
        print(f"HHI raw {hh.hhi_raw(vols):.4f}   normalized {hh.hhi_normalized(vols):.4f}   "
              f"top-10 {hh.top_k_share(vols,10)*100:.1f}%   largest {vols[0]/attr_total*100:.1f}%")

    mpath = DATA_DIR / "MANIFEST.json"
    man = json.load(open(mpath)) if mpath.exists() else {"sources": [], "files": {}}
    man.setdefault("sources", [])
    man.setdefault("files", {})
    man["sources"] = [s for s in man["sources"] if s.get("file") != "redemptions_by_wallet.csv"]
    man["sources"].append({
        "file": "redemptions_by_wallet.csv",
        "source": "Etherscan getLogs USDC Transfer (apikey from env, redacted)",
        "method": "FIFO burn-attribution: actual burns matched to the external deposits that funded them",
        "from_block": lo, "to_block": hi, "minter": minter,
        "gross_burned_usd": gross, "ext_inflow_usd": stats["ext_in"], "mint_inflow_usd": stats["mint_in"],
        "nonburn_outflow_usd": stats["nonburn_out"], "burn_attributed_usd": attr_total,
        "coverage_pct": coverage * 100 if coverage == coverage else None,
        "n_redeemers": n, "truncated": bool(tb or trunc),
        "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    man["files"]["redemptions_by_wallet.csv"] = {
        "sha256": hashlib.sha256(out_csv.read_bytes()).hexdigest(),
        "bytes": out_csv.stat().st_size,
    }
    json.dump(man, open(mpath, "w"), indent=2)
    print("MANIFEST updated (key-redacted).")


if __name__ == "__main__":
    main()
