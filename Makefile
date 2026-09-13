
.PHONY: docs test test-docker

PYTHON ?= python
REVISION ?= HEAD

test-docker:
	@test -n "$(REPORT)" || (echo 'Set REPORT to a new report directory'; exit 2)
	$(PYTHON) tools/validation/run.py --revision "$(REVISION)" --report "$(REPORT)" $(DOCKER_ARGS) -- make test

test:
	$(PYTHON) -m pip install --no-deps --no-build-isolation -e .
	$(PYTHON) -m pytest

test-lf:
	pytest --lf

debug:
	brownie run debug-price --network $(NETWORK)

debug-curve:
	brownie run debug-curve --network $(NETWORK)

test-chainlink:
	pytest tests/prices/test_chainlink.py

test-chainlink-lf:
	pytest tests/prices/test_chainlink.py --lf

docs:
	rm -r ./docs/source -f
	rm -r ./docs/_templates -f
	rm -r ./docs/_build -f
	sphinx-apidoc -o ./docs/source ./y
