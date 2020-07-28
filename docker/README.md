# ERPLibre - Docker

Those image are prepare to permit better portability and reproducibility of ERPLibre release.

Due the the growing code of ERPLibre, it could also simplify developpement.

NOTE : Those Dockerfile themselve are in heavy developpement for now. Incompatibilities between release are normal until the interfaces will be stabilized.


## Pre-requierments

- Basic knownledge with Docker, Linux and bash
- Latest Docker version

## Files representations

- Dockerfile.base : This Dockerfile represent the base Docker image layer reused by other child layersé
- Dockerfile.dev : This Dockerfile is specialized in developpement.
- Dockerfile.prod{pkg,src} : Dockerfile.prod.\* is a Docker image specialized for production systems. Dockerfile.prod.pkg reuse official debian files from Odoo.com. Dockerfile.prod.src fetch the Odoo source code as the ERPLibre runtime.


## Getting started

### Building the dockerimages

- docker build -f Dockerfile.base -t technolibre/erplibre-base:12.0 .
- docker build -f  Dockerfile.prod.pkg  .


### Running ERPLibre using Docker-Compose

1. Go at the root of this git project. Ex : `cd ERPLibre` 
2. docker-compose -f docker-compose.yml up
