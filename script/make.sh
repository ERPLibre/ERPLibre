#!/usr/bin/env bash
echo "
===> ${@}
"
time make $@
retVal=$?

echo "
<=== ${@}
"

if [[ $retVal -ne 0 ]]; then
    echo "Error make ${@}"
    exit 1
fi
