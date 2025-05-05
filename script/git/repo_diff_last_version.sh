#!/usr/bin/env bash

LAST_TAG=$(git describe --tags $(git rev-list --tags --max-count=1))
.venv.erplibre/bin/repo forall -pc "git diff ERPLibre/${LAST_TAG}..HEAD"

# For actual repo
git diff ${LAST_TAG}..HEAD
