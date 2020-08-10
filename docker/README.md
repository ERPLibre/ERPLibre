# ERPLibre - Docker

Those image are prepare to permit better portability and reproducibility of ERPLibre release.

Due the the growing code of ERPLibre, it could also simplify development.

NOTE: Those Dockerfile themselve are in heavy development for now. Incompatibilities between release are normal until the interfaces will be stabilized.


## Pre-requirements

- Basic knowledge with Docker, Linux and bash
- Latest Docker version

## Files representations

- Dockerfile.base: This Dockerfile represent the base Docker image layer reused by other child layers
- Dockerfile.dev: This Dockerfile is specialized in development.
- Dockerfile.prod{pkg,src}: Dockerfile.prod.\* is a Docker image specialized for production systems. Dockerfile.prod.pkg reuse official Debian files from Odoo.com. Dockerfile.prod.src fetch the Odoo source code as the ERPLibre runtime.

## Getting started

Be sure to start daemon docker
```bash
systemctl start docker
```

### Building the docker images

```bash
cd docker
docker build -f Dockerfile.base -t technolibre/erplibre-base:12.0 .
docker build -f Dockerfile.prod.pkg -t technolibre/erplibre:12.0-pkg .
```

### Running ERPLibre using Docker-Compose

Go at the root of this git project.
```bash
cd ERPLibre
docker-compose -f docker-compose.yml up -d
```

### Diagnostic Docker-Compose

Show docker-compose information
```bash
docker-compose ps
docker-compose logs IMAGE_NAME
```

Show docker information
```bash
docker ps -a
docker volume ls
docker inspect DOCKER_NAME
```

Connect to a running docker
```bash
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
```

Interesting command to debug
```bash
docker run -p 8069:8069 --entrypoint bash -ti DOCKER_NAME
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_USER=odoo -e POSTGRES_DB=postgres postgre

export
db_host = "host.docker.internal"

docker stats erplibre_ERPLibre_1
```

### Cleaning

Delete docker image
```bash
docker image prune
```

Delete volumes
```bash
docker-compose rm -v
```

Delete containers
```bash
docker rm $(docker ps -a | grep -v IMAGE | awk '{print $1}')
```

Delete volume
```bash
docker volume prune
```

# Need more space for docker
You can change the home for docker, edit file `/etc/docker/daemon.json`
```json
{
  "data-root": "/home/docker"
}
```
And restart docker service. You can delete all older location of docker or move it.

# Update docker
When building your docker with script
> ./script/docker_build.sh

You need to push your docker image and update your tag, like 1.0.1:
> docker push technolibre/erplibre:1.0.1
