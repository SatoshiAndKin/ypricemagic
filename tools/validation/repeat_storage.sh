#!/bin/sh
set -eu
cp /runner/workloads/test_bulk_memory.py /work/tests/test_bulk_memory.py
for repeat in timing-1 timing-2 timing-3; do
    mkdir -p "/reports/$repeat"
    VALIDATION_REPORT="/reports/$repeat" python /runner/storage_profile.py bulk
    VALIDATION_REPORT="/reports/$repeat" python /runner/storage_profile.py pools
done
mkdir -p /reports/allocations
VALIDATION_REPORT=/reports/allocations python /runner/storage_profile.py bulk --allocations
VALIDATION_REPORT=/reports/allocations python /runner/storage_profile.py pools --allocations
