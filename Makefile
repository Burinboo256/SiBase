PYTHON ?= python3
.PHONY: setup dev stop status test integration lint format typecheck build logs smoke lifecycle check
setup dev stop status test integration lint format typecheck build logs smoke lifecycle:
	$(PYTHON) scripts/phase1.py $@
check: lint typecheck test build

.PHONY: phase2-setup phase2-dev phase2-stop phase2-status phase2-test phase2-check phase2-integration phase2-recovery
phase2-setup phase2-dev phase2-stop phase2-status phase2-test phase2-check phase2-integration phase2-recovery:
	$(PYTHON) scripts/phase2.py $(patsubst phase2-%,%,$@)

.PHONY: phase3-dev phase3-prepare phase3-check phase3-integration phase3-status
phase3-dev phase3-prepare phase3-check phase3-integration phase3-status:
	$(PYTHON) scripts/phase3.py $(patsubst phase3-%,%,$@)
