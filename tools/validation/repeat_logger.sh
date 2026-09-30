#!/bin/sh
set -u
python -m pip install --no-deps --no-build-isolation -e . || exit $?
python /runner/check_compiled.py || exit $?
status=0
for mode in allocations timing; do
    for repetition in 1 2 3; do
        directory="/reports/${mode}-${repetition}"
        mkdir "$directory" || exit $?
        if [ "$mode" = allocations ]; then
            VALIDATION_REPORT="$directory" python /runner/logger_profile.py --allocations || status=$?
        else
            VALIDATION_REPORT="$directory" python /runner/logger_profile.py || status=$?
        fi
    done
done
exit "$status"
