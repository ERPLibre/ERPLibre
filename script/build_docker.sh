#!/usr/bin/env bash
cd docker
docker build -f Dockerfile.base -t technolibre/erplibre-base:12.0 .
docker build -f Dockerfile.prod.pkg -t technolibre/erplibre:12.0-pkg .
cd ..
docker-compose up -d
