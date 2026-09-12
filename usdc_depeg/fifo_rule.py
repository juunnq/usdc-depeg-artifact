"""A plain-language description of the FIFO redemption-attribution rule AS
IMPLEMENTED in redemptions.py's fifo_attribute() (and the merge/sort it feeds on),
not as its module docstring summarizes it. Where the two would read differently, this
module describes the CODE.

Written by reading redemptions.py:234-277 (fifo_attribute) in full, plus the event
construction that feeds it (redemptions.py:238-248) and the live-path caller
(redemptions.py:315).

Offline / keyless. Reads no data files, the rule is a property of the CODE, so this
module's only "input" is redemptions.py's source. Writes only results/fifo_rule.json
(never under data/).
"""
import json

from constants import RESULTS_DIR

OUT_FILE = RESULTS_DIR / "fifo_rule.json"


class FrozenPathWriteError(RuntimeError):
    """Raised if any write in this module is ever pointed at usdc_depeg/data/."""


def _guard_not_frozen(path) -> None:
    from constants import DATA_DIR
    data_dir = DATA_DIR.resolve()
    if data_dir in path.resolve().parents or path.resolve() == data_dir:
        raise FrozenPathWriteError(
            f"refusing to write '{path}': under usdc_depeg/data/, which is read-only. "
            f"fifo_rule.py may only write under results/."
        )


def rule() -> dict:
    return {
        "matching_window": (
            "A burn can draw on any deposit (external transfer-in, or a fresh mint) "
            "that reached the Circle minter address earlier in the SAME frozen "
            "block range [lo, hi] used for the whole run (redemptions.py:298-299, "
            "block_by_time over WINDOW_START_S..WINDOW_END_S), no matter how long "
            "before the burn it arrived -- there is no fixed per-burn lookback "
            "duration or expiry. The only thing that removes a deposit from "
            "eligibility is that it has already been fully drawn down by an earlier "
            "burn or non-burn outflow in chronological order. The single boundary "
            "is the window edge itself: a burn that would need to draw on a balance "
            "the minter already held before block `lo` cannot see it (the FIFO queue "
            "starts empty at `lo`), so that portion of the burn goes unmatched "
            "(counted as 'unbacked', see truncation below)."
        ),
        "matching_window_citation": "redemptions.py:234-248 (fifo_attribute, event "
                                     "construction), redemptions.py:298-299 (window "
                                     "block bounds lo/hi passed in)",
        "tie_break": (
            "Deposits and outflows are merged into one chronological event list and "
            "sorted by (blockNumber, logIndex) ascending -- i.e. on-chain execution "
            "order, with logIndex breaking ties between multiple events in the same "
            "block (a lower logIndex is treated as having happened first). Within a "
            "single burn's matching, there is no choice ever made between "
            "'equally eligible' deposits: the queue is strict FIFO (a deque), so the "
            "OLDEST unconsumed deposit is always drawn down first and completely "
            "before the next-oldest one is touched at all -- there is no pro-rata "
            "split across simultaneously-eligible deposits and no other ordering "
            "(e.g. largest-first, nearest-address-first) is applied anywhere in the "
            "code."
        ),
        "tie_break_citation": "redemptions.py:241-242 (sort key k(l) = (blockNumber, "
                               "logIndex)), redemptions.py:248 (events.sort), "
                               "redemptions.py:250,255-263 (deque q, consume() takes "
                               "from q[0] -- the front/oldest lot -- until exhausted "
                               "before advancing)",
        "batching": (
            "Streamed per-event, not batched. The code builds ONE merged, "
            "chronologically-sorted list of every inflow, burn, and non-burn "
            "outflow across the whole window (redemptions.py:244-248), then walks "
            "it in a single pass (redemptions.py:267-276), mutating one running "
            "FIFO queue as it goes. Each burn event calls consume() immediately "
            "against the queue's CURRENT state (redemptions.py:273, "
            "consume(v, True)) -- there is no grouping of burns into daily/hourly/ "
            "fixed-size batches, and no two-pass or windowed-aggregate design. A "
            "single burn event's own match can still span multiple deposits within "
            "one consume() call (the while loop at redemptions.py:255-263 keeps "
            "pulling from the queue front until the burn amount is covered or the "
            "queue is empty), but that is one event drawing on several lots, not "
            "several events being batched together."
        ),
        "batching_citation": "redemptions.py:244-248 (event list construction), "
                              "redemptions.py:254-265 (consume()), "
                              "redemptions.py:267-276 (single sequential pass)",
        "truncation": (
            "Two distinct cutoffs exist. (1) Unmatched burn remainder: if a burn's "
            "amount exceeds everything left in the FIFO queue, the leftover is NOT "
            "attributed to any sender -- it is added to stats['unbacked'] and simply "
            "dropped from the attributed totals (redemptions.py:264-265). This is "
            "the mechanism behind attribution coverage being < 100% of gross burns "
            "(MANIFEST-recorded coverage_pct 89.783% for the frozen run -> 10.217% "
            "of gross burn volume, ~$832.7M, uncovered). (2) API log-fetch "
            "truncation: transfer_logs()'s adaptive block-range splitting gives up "
            "after max_calls=8000 getLogs calls (redemptions.py:105-142, default "
            "cap at line 107) and returns truncated=True if it had to stop before "
            "covering the full requested range; that flag propagates through "
            "fifo_attribute()'s return (redemptions.py:277, `t1 or t2`) into the "
            "printed summary and the MANIFEST 'truncated' field "
            "(redemptions.py:332,350). For the frozen run this flag is recorded "
            "false (no log-fetch truncation occurred), so all coverage loss in the "
            "frozen CSV is cutoff (1), not cutoff (2)."
        ),
        "truncation_citation": "redemptions.py:254-265 (consume(), stats['unbacked']), "
                                "redemptions.py:105-142 (transfer_logs, max_calls cap), "
                                "redemptions.py:277 (truncated = t1 or t2), "
                                "redemptions.py:332,350 (printed / MANIFEST truncated flag)",
        "uncovered_10pct_note": (
            "The FIFO burn-attribution boundary: the uncovered 10.217% "
            "of gross burn volume (MANIFEST coverage_pct 89.78296302535323 on the "
            "frozen redemptions_by_wallet.csv) cannot be characterized further "
            "offline. What is frozen and hashed is the attribution's OUTPUT -- the "
            "776-row (wallet, volume) table -- not its INPUT: the raw per-event "
            "Etherscan Transfer log that fifo_attribute() consumes is held only in "
            "memory during a live run and is never written to disk anywhere in this "
            "repo (redemptions.py has no per-event/per-block output path). Without "
            "that log there is no way, offline, to say for a given uncovered dollar "
            "whether it was unbacked (drew on a pre-window minter balance), lost to "
            "a getLogs truncation, or something else -- reconstructing that would "
            "require a live, keyed Etherscan pull (ETHERSCAN_API_KEY), which this "
            "offline reproduction path does not have and must not perform."
        ),
        "uncovered_10pct_note_citation": "data/MANIFEST.json sources[] entry for "
                                     "redemptions_by_wallet.csv (coverage_pct "
                                     "89.78296302535323)",
    }


def main():
    _guard_not_frozen(OUT_FILE)
    RESULTS_DIR.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(rule(), indent=2), encoding="utf-8")
    print(f"wrote {OUT_FILE}")


if __name__ == "__main__":
    main()
