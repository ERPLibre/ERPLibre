#!/usr/bin/env bash
# This will format all python file
# argument 1: directory or file to format
NPROC=$(nproc)
source ./script/OCA_maintainer-tools/env/bin/activate
oca-autopep8 -j ${NPROC} --max-line-length 100 -ari $@
