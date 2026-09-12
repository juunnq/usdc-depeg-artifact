"""Every number the short paper prints must also appear in the regular paper.

D28 builds the short version as a rewrite to budget, and requires that every number and
citation be carried VERBATIM from the regular text. The regular text is the one whose
numbers are claim-mapped, gated, and traced to results files, so "carried verbatim from
the regular text" is what makes the short version's numbers provenanced at all. It
replaces the printed claim map with an artifact URL, so nothing inside the short paper
records where its numbers came from.

That makes containment the invariant worth testing: a numeric literal in the short paper
that does NOT occur in the regular paper was either invented, re-rounded, or mistyped
during the rewrite, and no other check in this repository would see it. The eight
sections were written in parallel by separate writers working from the regular sources,
which is exactly the arrangement in which a silently re-rounded figure is most likely.

Direction matters: containment is one-way. The regular paper prints many numbers the
short version drops, which is the whole point of an 8-page variant, so the reverse
inclusion is not asserted.

Two numbers are authorized exceptions. G9's short-track reviewers raised both as Tier-1
defects in the regular text that the short version was told to fix, so for these two the
short version is deliberately NOT a copy. They are listed in AUTHORIZED_DIVERGENCE below,
each with the results key it resolves through, and the second test re-derives each one from
that key -- so the exception is gated on provenance rather than simply excused.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from constants import PKG_DIR

RESULTS = PKG_DIR / "results"

# number printed in the short version -> (results file, key, why it is not in the regular)
AUTHORIZED_DIVERGENCE = {
    # S-2. A reviewer back-solved Kraken's close trough to ~$0.901 and concluded the paper
    # contradicts itself, because Section 3 calls Kraken a cross-check on the $0.877 trough
    # while Section 4 reads 19.2% off Kraken's close. Both are true of DIFFERENT Kraken
    # statistics. Printing the close minimum once is what makes them visibly consistent.
    "0.901": ("trough_corroboration.json",
              "firing_report.series.kraken_usdc_close.min_print"),
    # S-10. The regular text prints lag-1 autocorrelation 0.96 and an effective sample size
    # of 4.0. Those two do not reconcile: 212*(1-0.96)/(1+0.96) = 4.33. The results file
    # holds 0.9631, which gives 3.985 -> 4.0. The short version prints the precision that
    # reproduces its own printed figure; the regular version is frozen and keeps 0.96.
    "0.963": ("impossibility_window.json", "coins.USDC.independence.lag1_autocorr"),
}

PAPER = PKG_DIR.parent / "paper"
REG_SECTIONS = PAPER / "fc27" / "sections"
SHORT_SECTIONS = PAPER / "fc27short" / "sections"
SHORT_TEX = PAPER / "fc27short" / "fc27short.tex"

# Arguments that carry digits which are names, not quantities.
_OPAQUE = re.compile(
    r"\\(?:cite|ref|eqref|label|input|includegraphics|url|path|bibliography"
    r"|bibliographystyle|documentclass|usepackage|newlength|newcommand"
    r"|PassOptionsToPackage|setlength|settowidth|pdftrailerid)\s*(?:\[[^\]]*\])?\{[^}]*\}")
# Typesetting dimensions and column specs: 1.5em, 0mu, p{2.1cm}, 0.93\linewidth, 12.2cm.
_DIMEN = re.compile(r"-?\d*\.?\d+\s*(?:em|ex|pt|mu|cm|mm|in|\\linewidth|\\textwidth)")
_COLSPEC = re.compile(r"[pmb]\{[^}]*\}")
_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)

# A numeric literal as the manuscript writes one: 0.877, 1233, 12.3, 1{,}233, 8.
_NUMBER = re.compile(r"\d[\d{},.]*\d|\d")


def _numbers(text: str) -> set[str]:
    text = _COMMENT.sub(" ", text)
    text = _OPAQUE.sub(" ", text)
    text = _COLSPEC.sub(" ", text)
    text = _DIMEN.sub(" ", text)
    out = set()
    for tok in _NUMBER.findall(text):
        tok = tok.replace("{,}", "").replace(",", "")
        tok = tok.rstrip(".")
        if tok:
            out.add(tok)
    return out


def _read(paths) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


def test_every_number_in_the_short_paper_occurs_in_the_regular_paper():
    if not SHORT_SECTIONS.exists():
        pytest.skip("short version not present on this branch")
    short_files = sorted(SHORT_SECTIONS.glob("*.tex"))
    assert short_files, "paper/fc27short/sections/ has no .tex files"

    short_src = _read(short_files)
    if SHORT_TEX.exists():
        # The skeleton carries the figure and table captions, which are prose the
        # assembly wrote rather than a writer, and are just as able to carry an
        # invented number.
        short_src += "\n" + SHORT_TEX.read_text(encoding="utf-8")

    # The regular paper's generated table fragments are part of the regular paper, and
    # several figures the short version legitimately carries are printed only there --
    # share_range.tex, for instance, is where 19.2% and 35.1% appear. Reading only
    # sections/ made the corpus too narrow and reported a verbatim carry as an invention.
    regular_src = _read(sorted(REG_SECTIONS.glob("*.tex"))
                         + sorted((REG_SECTIONS.parent / "tables").glob("*.tex")))

    short_nums = _numbers(short_src)
    regular_nums = _numbers(regular_src)

    invented = sorted(short_nums - regular_nums - set(AUTHORIZED_DIVERGENCE),
                      key=lambda s: (len(s), s))
    assert not invented, (
        f"{len(invented)} number(s) printed in the short paper do not occur anywhere in "
        f"the regular paper, so they are not carried verbatim and have no provenance: "
        f"{invented}"
    )


def test_each_authorized_divergence_is_still_printed_and_still_resolves():
    """The allow-list is the one hole in containment, so it is gated at both ends.

    A number stops being an authorized divergence the moment it stops being printed (the
    entry is then stale and hides a future invention) or stops matching the results key it
    names (the entry is then a licence to print anything).
    """
    if not SHORT_SECTIONS.exists():
        pytest.skip("short version not present on this branch")
    short_nums = _numbers(_read(sorted(SHORT_SECTIONS.glob("*.tex"))))

    for printed, (filename, key) in sorted(AUTHORIZED_DIVERGENCE.items()):
        assert printed in short_nums, (
            f"{printed} is allow-listed as an authorized divergence but the short paper no "
            f"longer prints it; delete the entry rather than leaving the hole open"
        )
        path = RESULTS / filename
        assert path.exists(), f"{printed}: results file {filename} is missing"
        found = _resolve(json.loads(path.read_text(encoding="utf-8")), key)
        assert found is not None, f"{printed}: {filename} has no key {key!r}"
        # The printed figure is the stored value rounded to the precision printed.
        assert round(float(found), len(printed.split(".")[1])) == float(printed), (
            f"{printed} no longer rounds from {filename}:{key} = {found}"
        )


def _resolve(doc, key):
    """Walk a dotted key path through a results document.

    A path, not a search: `min_print` occurs under six different series in
    trough_corroboration.json, and a search would have bound Kraken's close to the
    composite's trough without complaining.
    """
    node = doc
    for segment in key.split("."):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


def test_short_paper_cites_only_keys_the_regular_paper_cites():
    """Same argument, for citations. A key the regular paper never cites has not been
    through its bibliography verification."""
    if not SHORT_SECTIONS.exists():
        pytest.skip("short version not present on this branch")
    cite_re = re.compile(r"\\cite\{([^}]*)\}")

    def keys(text):
        out = set()
        for group in cite_re.findall(_COMMENT.sub(" ", text)):
            out.update(k.strip() for k in group.split(",") if k.strip())
        return out

    short_keys = keys(_read(sorted(SHORT_SECTIONS.glob("*.tex"))))
    regular_keys = keys(_read(sorted(REG_SECTIONS.glob("*.tex"))))
    unknown = sorted(short_keys - regular_keys)
    assert not unknown, (
        f"short paper cites key(s) the regular paper does not: {unknown}"
    )
