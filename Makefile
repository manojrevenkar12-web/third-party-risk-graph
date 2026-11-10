PY ?= python3
export PYTHONPATH := src

.PHONY: world test eval gate heldout report web check

world:     ## regenerate and re-pin the world (only before the held-out run)
	$(PY) scripts/build_world.py
test:
	$(PY) -m pytest -q
eval:      ## every design on the development split -> reports/dev.json (~10 min)
	$(PY) scripts/evaluate.py
gate:      ## CI: the graph pipeline on the development split; exits 1 if it fails the gate (~1 min)
	$(PY) scripts/gate.py
heldout:   ## once: every design on the held-out split -> reports/heldout.json
	$(PY) scripts/heldout.py
report:    ## README tables and the dashboard's data from reports/*.json
	$(PY) scripts/report.py
web:
	cd web && npm ci && npm test && npm run build
check: test gate
