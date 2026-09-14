#!/bin/sh
set -eu
for repeat in timing-1 timing-2 timing-3; do
    mkdir -p "/reports/$repeat"
    VALIDATION_REPORT="/reports/$repeat" python /runner/cache_profile.py
done
mkdir -p /reports/allocations
VALIDATION_REPORT=/reports/allocations python /runner/cache_profile.py --allocations
