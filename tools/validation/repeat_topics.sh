#!/bin/sh
set -eu
for repeat in timing-1 timing-2 timing-3; do
    mkdir -p "/reports/$repeat"
    YPRICEMAGIC_SQLITE_PATH="/data/topics-$repeat.sqlite" VALIDATION_REPORT="/reports/$repeat" python /runner/topic_profile.py
done
mkdir -p /reports/allocations
YPRICEMAGIC_SQLITE_PATH=/data/topics-allocations.sqlite VALIDATION_REPORT=/reports/allocations python /runner/topic_profile.py --allocations
