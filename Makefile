# Recoil — make targets (POSIX). On Windows without make, use the equivalent
# commands listed in README.md or scripts/demo.ps1.

PY := $(shell [ -f .venv/Scripts/python ] && echo .venv/Scripts/python || echo .venv/bin/python)

.PHONY: setup seed dev demo doctor test demo-check api web

setup:
	python -m venv .venv
	$(PY) -m pip install -e ".[dev]"
	cd web && npm install --no-audit --no-fund
	$(PY) -m recoil.cli reset --demo
	$(PY) -m recoil.cli doctor

seed:
	$(PY) -m recoil.cli reset --demo

api:
	$(PY) -m uvicorn server.main:app --port 8787

web:
	cd web && npm run dev

# run API + web together with prefixed logs; single Ctrl-C tears both down
dev:
	@trap 'kill 0' INT TERM; \
	( $(PY) -m uvicorn server.main:app --port 8787 --log-level warning 2>&1 | sed 's/^/[api] /' & ) ; \
	( cd web && npm run dev 2>&1 | sed 's/^/[web] /' & ) ; \
	wait

demo:
	bash scripts/demo.sh

doctor:
	$(PY) -m recoil.cli doctor

demo-check:
	$(PY) -m recoil.cli demo-check

test:
	$(PY) -m pytest -q
