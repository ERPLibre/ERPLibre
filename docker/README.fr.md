
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

```bash
systemctl start docker
```

### Construire les images docker

```bash
cd docker
docker build -f Dockerfile.base -t technolibre/erplibre-base:12.0 .
docker build -f Dockerfile.prod.pkg -t technolibre/erplibre:12.0-pkg .
```

### Exécuter ERPLibre avec Docker-Compose

Allez à la racine de ce projet git.

```bash
cd ERPLibre
docker compose -f docker-compose.yml up -d
```

### Diagnostic Docker-Compose

Afficher les informations docker-compose

```bash
docker compose ps
docker compose logs IMAGE_NAME
```

Afficher les informations docker

```bash
docker ps -a
docker volume ls
docker inspect DOCKER_NAME
```

Se connecter à un docker en cours d'exécution

```bash
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
```

Commandes pour le débogage

```bash
docker run -p 8069:8069 --entrypoint bash -ti DOCKER_NAME
docker exec -ti DOCKER_NAME bash
docker exec -u root -ti DOCKER_NAME bash
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -e POSTGRES_USER=odoo -e POSTGRES_DB=postgres postgre

export
db_host = "host.docker.internal"

docker stats erplibre_ERPLibre_1
```

### Nettoyage

Supprimer tout le système

```bash
docker system prune -a
```

Supprimer une image docker

```bash
docker image prune
docker rmi $(docker images -q)
```

Supprimer les volumes

```bash
docker compose rm -v
```

Supprimer les conteneurs

```bash
docker rm $(docker ps -a | grep -v IMAGE | awk '{print $1}')
```

Supprimer un volume

```bash
docker volume prune
```

# Changer le répertoire docker
Vous pouvez changer le répertoire docker en modifiant le fichier `/etc/docker/daemon.json`

```json
{
  "data-root": "/home/docker"
}
```

Et redémarrez le service docker. Vous pouvez supprimer ou déplacer tous les anciens emplacements de docker.

Ou

Ajoutez `--data-root /second_drive/docker` comme dans l'exemple suivant dans le fichier `/lib/systemd/system/docker.service` :

```
ExecStart=/usr/bin/dockerd --data-root /second_drive/docker -H fd:// --containerd=/run/containerd/containerd.sock
```

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
