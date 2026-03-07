<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# ERPLibre - Docker

Those images are prepared to permit better portability and reproducibility of ERPLibre release.

Due the growing code of ERPLibre, it could also simplify development.

NOTE: Those Dockerfiles themselves are in heavy development for now. Incompatibilities between releases are normal until the interface is stabilized.

## Pre-requirements

- Basic knowledge with Docker, Linux and bash
- Latest Docker version

## Files representations

- Dockerfile.base: This Dockerfile represents the base Docker image layer reused by other child layers.
- Dockerfile.dev: This Dockerfile is specialized in development.
- Dockerfile.prod{pkg,src}: Dockerfile.prod.\* is a Docker image specialized for production systems. Dockerfile.prod.pkg reuses official Debian files from Odoo.com. Dockerfile.prod.src fetches the Odoo source code as the ERPLibre runtime.

## Getting started

Be sure to start daemon docker

<!-- [fr] -->
# ERPLibre - Docker

Ces images sont préparées pour permettre une meilleure portabilité et reproductibilité des versions d'ERPLibre.

En raison du code croissant d'ERPLibre, cela pourrait aussi simplifier le développement.

NOTE : Ces Dockerfiles sont en développement actif pour le moment. Les incompatibilités entre les versions sont normales jusqu'à ce que l'interface soit stabilisée.

## Prérequis

- Connaissances de base avec Docker, Linux et bash
- Dernière version de Docker

## Représentation des fichiers

- Dockerfile.base : Ce Dockerfile représente la couche d'image Docker de base réutilisée par les autres couches enfants.
- Dockerfile.dev : Ce Dockerfile est spécialisé pour le développement.
- Dockerfile.prod{pkg,src} : Dockerfile.prod.\* est une image Docker spécialisée pour les systèmes de production. Dockerfile.prod.pkg réutilise les fichiers Debian officiels d'Odoo.com. Dockerfile.prod.src récupère le code source d'Odoo comme environnement d'exécution ERPLibre.

## Démarrage

Assurez-vous de démarrer le démon docker

<!-- [common] -->
```bash
systemctl start docker
```

<!-- [en] -->
### Building the docker images

<!-- [fr] -->
### Construire les images docker

<!-- [common] -->
```bash
cd docker
docker build -f Dockerfile.base -t technolibre/erplibre-base:12.0 .
docker build -f Dockerfile.prod.pkg -t technolibre/erplibre:12.0-pkg .
```

<!-- [en] -->
### Running ERPLibre using Docker-Compose

Go at the root of this git project.

<!-- [fr] -->
### Exécuter ERPLibre avec Docker-Compose

Allez à la racine de ce projet git.

<!-- [common] -->
```bash
cd ERPLibre
docker compose -f docker-compose.yml up -d
```

<!-- [en] -->
### Diagnostic Docker-Compose

Show docker-compose information

<!-- [fr] -->
### Diagnostic Docker-Compose

Afficher les informations docker-compose

<!-- [common] -->
```bash
docker compose ps
docker compose logs IMAGE_NAME
```

<!-- [en] -->
Show docker information

<!-- [fr] -->
Afficher les informations docker

<!-- [common] -->
```bash
docker ps -a
docker volume ls
docker inspect DOCKER_NAME
```

<!-- [en] -->
Connect to a running docker

<!-- [fr] -->
Se connecter à un docker en cours d'exécution

<!-- [common] -->
```bash
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
```

<!-- [en] -->
Commands for debugging

<!-- [fr] -->
Commandes pour le débogage

<!-- [common] -->
```bash
docker run -p 8069:8069 --entrypoint bash -ti DOCKER_NAME
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_USER=odoo -e POSTGRES_DB=postgres postgre

export
db_host = "host.docker.internal"

docker stats erplibre_ERPLibre_1
```

<!-- [en] -->
### Cleaning

Delete all system

<!-- [fr] -->
### Nettoyage

Supprimer tout le système

<!-- [common] -->
```bash
docker system prune -a
```

<!-- [en] -->
Delete docker image

<!-- [fr] -->
Supprimer une image docker

<!-- [common] -->
```bash
docker image prune
docker rmi $(docker images -q)
```

<!-- [en] -->
Delete volumes

<!-- [fr] -->
Supprimer les volumes

<!-- [common] -->
```bash
docker compose rm -v
```

<!-- [en] -->
Delete containers

<!-- [fr] -->
Supprimer les conteneurs

<!-- [common] -->
```bash
docker rm $(docker ps -a | grep -v IMAGE | awk '{print $1}')
```

<!-- [en] -->
Delete volume

<!-- [fr] -->
Supprimer un volume

<!-- [common] -->
```bash
docker volume prune
```

<!-- [en] -->
# Change docker directory
You can change the docker directory by editing file `/etc/docker/daemon.json`

<!-- [fr] -->
# Changer le répertoire docker
Vous pouvez changer le répertoire docker en modifiant le fichier `/etc/docker/daemon.json`

<!-- [common] -->
```json
{
  "data-root": "/home/docker"
}
```

<!-- [en] -->
And restart docker service. You can delete or move all older locations of docker.

Or

Add `--data-root /second_drive/docker` like example following into file `/lib/systemd/system/docker.service` :

<!-- [fr] -->
Et redémarrez le service docker. Vous pouvez supprimer ou déplacer tous les anciens emplacements de docker.

Ou

Ajoutez `--data-root /second_drive/docker` comme dans l'exemple suivant dans le fichier `/lib/systemd/system/docker.service` :

<!-- [common] -->
```
ExecStart=/usr/bin/dockerd --data-root /second_drive/docker -H fd:// --containerd=/run/containerd/containerd.sock
```

<!-- [en] -->
# Update docker
When building your docker with script
> make docker_build_odoo_18

List your docker version
> docker images

You need to push your docker image and update your tag, like 1.0.1:
> docker push technolibre/erplibre:VERSION

# Diagnostic
When getting and error about missing module, or after an upgrade, you need to update config file.
> make docker_exec_erplibre_gen_config

<!-- [fr] -->
# Mettre à jour docker
Lors de la construction de votre docker avec le script
> make docker_build_odoo_18

Listez vos versions docker
> docker images

Vous devez pousser votre image docker et mettre à jour votre tag, comme 1.0.1 :
> docker push technolibre/erplibre:VERSION

# Diagnostic
Lorsque vous obtenez une erreur de module manquant, ou après une mise à jour, vous devez mettre à jour le fichier de configuration.
> make docker_exec_erplibre_gen_config
