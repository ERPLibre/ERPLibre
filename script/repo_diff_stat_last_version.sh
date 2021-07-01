#!/usr/bin/env bash

LAST_TAG=$(git describe --tags $(git rev-list --tags --max-count=1))
./.venv/repo forall -pc "git diff --stat ERPLibre/${LAST_TAG}..HEAD"

# For actual repo
git diff --stat ${LAST_TAG}..HEAD
