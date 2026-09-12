# Trimmed from the repository's paper/Makefile: fc27-build variables and
# targets only. The non-anonymized `paper` build (paper.tex) is
# intentionally not part of this artifact.
PAPER = paper
FC27DIR = fc27

# Anonymized FC'27 submission build. tools/build_fc27.py owns the whole recipe --
# regenerating figures/tables, cross-checking every \includegraphics target against
# what was actually produced (failing loudly on a mismatch, rather than silently
# building from a stale paper/fc27/figs/ copy, which is what this target's own
# hand-maintained `cp` lines used to risk), SOURCE_DATE_EPOCH, and the pdflatex/
# bibtex sequence. This target is now a one-line call into it.
fc27:
	python ../tools/build_fc27.py


fc27-clean:
	rm -f $(FC27DIR)/fc27.aux $(FC27DIR)/fc27.bbl $(FC27DIR)/fc27.blg \
	      $(FC27DIR)/fc27.log $(FC27DIR)/fc27.out


clean:
	rm -f $(PAPER).aux $(PAPER).bbl $(PAPER).blg $(PAPER).log $(PAPER).out


cleanall: clean
	rm -f $(PAPER).pdf


.PHONY: all clean cleanall fc27 fc27-clean
