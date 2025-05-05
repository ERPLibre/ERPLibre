#!/usr/bin/env bash

Color_Off='\033[0m' # Text Reset
BOLD='\033[1m'      # Black

LAST_TAG=$(git describe --tags $(git rev-list --tags --max-count=1))
.venv.erplibre/bin/repo forall -pc "git diff --stat ERPLibre/${LAST_TAG}..HEAD"

echo ""
echo -e "${BOLD}project /${Color_Off}"

# For actual repo
git diff --stat ${LAST_TAG}..HEAD
