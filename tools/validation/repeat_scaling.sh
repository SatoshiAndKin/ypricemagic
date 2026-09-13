#!/bin/sh
set -u
python -m pip install --no-deps --no-build-isolation -e . || exit $?
python /runner/check_compiled.py || exit $?
status=0
for repetition in 1 2 3; do
    directory="/reports/timing-${repetition}"
    mkdir "$directory" || exit $?
    VALIDATION_REPORT="$directory" python /runner/scaling_profile.py || status=$?
done
mkdir /reports/allocations || exit $?
VALIDATION_REPORT=/reports/allocations python /runner/scaling_profile.py --allocations || status=$?
exit "$status"
