#!/bin/sh
set -eu
python /runner/probe.py
# Prepare every source revision: older Makefiles expect extensions to exist.
python -m pip install --no-deps --no-build-isolation -e .
# Use the required command unchanged. Settings and reporting live in project config.
PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test
python /runner/check_compiled.py
