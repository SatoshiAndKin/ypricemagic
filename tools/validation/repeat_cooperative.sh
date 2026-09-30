#!/bin/sh
set -u
status=0
for repetition in 1 2 3; do
    directory="/reports/repetition-${repetition}"
    mkdir "$directory" || exit $?
    VALIDATION_REPORT="$directory" python /runner/cooperative_profile.py || status=$?
    # Each repeat has its own process and report. Remove only the generated test
    # directory between independent measurements, not any runtime cache.
    rm -r /tmp/cooperative-profile
done
exit "$status"
