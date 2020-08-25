#!/usr/bin/env bash
cd docker

ARGS=--build-arg=WORKING_BRANCH=$(git rev-parse --abbrev-ref HEAD)
set -e
# Build base
docker build ${ARGS} -f Dockerfile.base -t technolibre/erplibre-base:1.0.1 .

# Build prod
docker build ${ARGS} -f Dockerfile.prod.pkg -t technolibre/erplibre:1.0.1 .

cd ..
docker-compose up -d
