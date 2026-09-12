"""Pins the plain-language FIFO rule description against the actual
redemptions.py code it describes, so a future edit to fifo_attribute() cannot
silently leave this description wrong."""
from pathlib import Path

import pytest

import fifo_rule as fr
import redemptions
from constants import DATA_DIR


REQUIRED_FIELDS = ("matching_window", "tie_break", "batching", "truncation",
                    "uncovered_10pct_note")


def test_all_required_fields_present_and_nonempty():
    r = fr.rule()
    for field in REQUIRED_FIELDS:
        assert field in r
        assert isinstance(r[field], str) and len(r[field]) > 20
        assert f"{field}_citation" in r


def test_citations_reference_real_lines_in_redemptions_py():
    """Every function/line cited must actually exist at that name in redemptions.py --
    a cheap guard against a citation drifting out of date."""
    src_path = Path(redemptions.__file__)
    src_lines = src_path.read_text(encoding="utf-8").splitlines()
    # spot-check the anchors each field's citation depends on
    assert "def fifo_attribute(minter, lo, hi):" in src_lines[233]  # line 234, 0-indexed
    assert "events.sort(key=lambda e: e[0])" in src_lines[247]      # line 248
    assert "stats[\"unbacked\"] += amount" in src_lines[264]        # line 265
    assert "def transfer_logs(" in src_lines[104]                   # line 105
    assert "return attributed, stats, (t1 or t2)" in src_lines[276]  # line 277


def test_matching_window_describes_whole_run_window_not_a_lookback():
    r = fr.rule()
    text = r["matching_window"].lower()
    assert "no fixed per-burn lookback" in text or "no matter how long" in text


def test_tie_break_describes_strict_fifo_not_prorata():
    r = fr.rule()
    text = r["tie_break"].lower()
    assert "oldest" in text
    assert "pro-rata" in text or "no pro-rata" in text


def test_batching_says_streamed_not_batched():
    r = fr.rule()
    assert r["batching"].startswith("Streamed per-event, not batched.")


def test_uncovered_10pct_matches_manifest_coverage():
    """Pin the uncovered share against the frozen MANIFEST coverage_pct directly,
    not just against the prose."""
    import json
    man = json.loads((DATA_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    src = next(s for s in man["sources"] if s["file"] == "redemptions_by_wallet.csv")
    uncovered_pct = 100.0 - src["coverage_pct"]
    assert uncovered_pct == pytest.approx(10.217, abs=1e-3)
    assert "10.217%" in fr.rule()["uncovered_10pct_note"]


def test_uncovered_note_says_offline_uncharacterizable():
    text = fr.rule()["uncovered_10pct_note"].lower()
    assert "cannot be characterized further offline" in text
    assert "etherscan_api_key" in text


def test_guard_refuses_to_write_under_data_dir():
    with pytest.raises(fr.FrozenPathWriteError):
        fr._guard_not_frozen(DATA_DIR / "some_new_file.json")
