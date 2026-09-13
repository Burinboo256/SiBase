PYTHON ?= python3
.PHONY: setup dev stop status test integration lint format typecheck build logs smoke lifecycle check
setup dev stop status test integration lint format typecheck build logs smoke lifecycle:
	$(PYTHON) scripts/phase1.py $@
check: lint typecheck test build
