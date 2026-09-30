#!/bin/sh
set -eu
# Copy the same frozen fixture into both source revisions.
cp /runner/workloads/test_event_memory.py /work/tests/test_event_memory.py
for repeat in timing-1 timing-2 timing-3; do
    mkdir -p "/reports/$repeat"
    VALIDATION_REPORT="/reports/$repeat" python /runner/event_profile.py
done
mkdir -p /reports/allocations
VALIDATION_REPORT=/reports/allocations python /runner/event_profile.py --allocations
