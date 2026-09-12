# Anonymized artifact, FC 2027 submission

This is a content export: a snapshot of files, not a git clone. It carries no commit history from the source repository.

## The two manuscripts

One body of work was written up as two separate submissions, built by one script from one set of generated figures and table fragments.

| | Path | Pages | SHA-256 of the built PDF |
|---|---|---|---|
| **Short paper (SUBMITTED)** | `paper/fc27short/fc27short.pdf` | 8 of main text, 11 including references | `e5bf1efd5a843c3cfa0f8aa321415b632595db7a30a694e541e5beed73f32662` |
| Regular paper (not submitted) | `paper/fc27/fc27.pdf` | 15 of main text, 26 including references and appendices | `66da628e861f5d61644bb4637aa524c30bd91af207c9f05f6aaf4285ffdc45c8` |

**The short paper is the submission.** The regular version is included because it is the source of every number the short paper carries and it holds the printed claim map, the redemption-concentration result and the appendices that the 8-page budget excluded. It is kept correct, and it is not under review.

## Layout

- `usdc_depeg/`, the analysis package: code, the frozen data snapshot (`data/`, `data/MANIFEST.json`), computed results (`results/`), generated figures (`figs/`), and the test suite (`tests/`).
- `paper/fc27short/`, the submitted manuscript: `fc27short.tex`, its sections, table fragments (`tables/`), figures (`figs/`), and the built PDF.
- `paper/fc27/`, the regular manuscript: `fc27.tex`, `refs.bib`, table fragments, figures, and the built PDF. Both papers share `paper/fc27/refs.bib`.
- `paper/Makefile`, trimmed to the `fc27` build target.
- `EXPORT_MANIFEST.sha256`, SHA-256 of every file in this export (`sha256sum -c EXPORT_MANIFEST.sha256` to verify after transfer).
- `.gitattributes`, marking every file `-text` so the stored bytes are the bytes the manifest attests.

## Reproduction

Requires Python 3 with the packages in `usdc_depeg/requirements.txt`, and a LaTeX distribution providing the `llncs` document class and `splncs04` bibliography style (both are standard Springer LNCS files; not vendored here since they are not part of this repository's own history).

From `usdc_depeg/`, offline and keyless (no `ETHERSCAN_API_KEY` is read or required):

```
python data_fetch.py verify           # check data/*.csv against MANIFEST.json's hashes
python data_fetch_n1.py verify        # same check for the N1 cross-venue series
python redemptions.py --from-frozen   # re-validate the frozen FIFO attribution
python -m pytest                      # full test suite
python report.py                      # regenerate every results/*.json, every
                                       # figure, and every paper table fragment
```

Then, from the export root, build either or both manuscripts:

```
python tools/build_fc27.py --target short    # the submitted paper
python tools/build_fc27.py --target regular  # the long version
python tools/build_fc27.py --target both
```

Each build is byte-reproducible: `SOURCE_DATE_EPOCH` is pinned by the build script and `\pdftrailerid{}` is empty, so a rebuild of unmodified source reproduces the SHA-256 in the table above. The build fails rather than warns on an undefined reference, a multiply-defined label, an over-wide table, a float too large for the page, or any text set outside the page box.

None of these steps overwrites an already-frozen file under `data/`, and none requires network access.

## Line endings

Text files here use LF. The frozen snapshot under `usdc_depeg/data/` keeps its original bytes, because `usdc_depeg/data/MANIFEST.json` pins a SHA-256 over each of them and rewriting a line ending there would break that check. `EXPORT_MANIFEST.sha256` is computed after normalization, so it attests the bytes this repository actually stores and serves.
