
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


`.venv.erplibre` est bâti sur le Python de l'image, celui d'Odoo, sans mise ni
pyenv. La construction s'arrête quand ce Python ne sait pas lire `script/`, ce
qui arrive avec une version d'Odoo dépréciée.

### Exécuter ERPLibre avec Docker-Compose

Allez à la racine de ce projet git.

```bash
cd ERPLibre
docker compose -f docker-compose.yml up -d
```

### Paquets Python supplémentaires pour les addons

Un addon, ou un script d'ERPLibre, peut demander un paquet Python que l'image
n'a pas. Listez-les sur une ligne, séparés par des espaces, avec une version
quand elle compte ; une contrainte ne contient ni espace ni guillemet. Chaque
venv de l'image a sa liste : `PIP_EXTRA_REQUIREMENTS_ODOO` pour le venv d'Odoo,
celui qu'importent les addons, et `PIP_EXTRA_REQUIREMENTS_ERPLIBRE` pour
`.venv.erplibre`, celui des outils de `script/` :

```yaml
    environment:
      PIP_EXTRA_REQUIREMENTS_ODOO: "humanize pyotp==2.9.0 phonenumbers>=8.13,<9"
      PIP_EXTRA_REQUIREMENTS_ERPLIBRE: ""
```

À chaque démarrage, `docker/entrypoint_pip_extra.sh` installe chaque liste
avec le pip de son venv, puis lance Odoo sous `odoo` : le conteneur démarre en
root pour que chaque pip tourne sous le propriétaire de son venv,
l'`ERPLIBRE_CODE_OWNER` de la construction. Une exigence déjà satisfaite ne
télécharge rien. Une exigence que pip ne peut pas installer arrête le conteneur
avant Odoo, avec l'erreur de pip dans `docker compose logs`.

Root ne garde que les deux capacités dont setpriv a besoin (`cap_drop`,
`cap_add`), et `no-new-privileges` empêche Odoo d'en regagner une. Comme le
conteneur démarre en root, `docker exec` ouvre un shell root par défaut : un
fichier qu'il écrit dans le filestore ou dans `/etc/odoo` appartient à root, et
Odoo ne peut plus le modifier. Passez le compte :

```bash
docker compose exec -u odoo ERPLibre bash
```

### Tirer le code depuis Odoo

`erplibre_info_git_fetch` fait le fetch et le tirage des clones git depuis
Odoo, ce qui demande deux choses au conteneur :

- le code et ses dépôts git appartiennent au compte qui fait tourner Odoo.
  L'image se construit avec `ERPLIBRE_CODE_OWNER=odoo`, la valeur par défaut ;
  `root` construit une image qu'Odoo ne peut pas réécrire, et
  `script/git/repo_pull.py` refuse ses clones en nommant leur propriétaire. Les
  images d'ERPLibre 1.6.0 et antérieures laissent le code à root :
  `script/update/docker_fix_erplibre_info_docker_erplibre_160.sh` ne prépare un
  tel conteneur que pour les instantanés d'`erplibre_info_git`, et son dernier
  message nomme la condition qui manque ;
- Odoo tourne avec une valeur de `--dev` :

```yaml
    command: odoo --dev=all
```

Écrivez le `=` : l'entrée de l'image ajoute ses arguments de base de données
après la commande, et un `--dev` seul prend le suivant, `--db_host`, pour
valeur. Odoo 18 ne lit `--dev` que sur la ligne de commande, une ligne
`dev_mode` d'`odoo.conf` est ignorée. `all` active `reload`, `qweb` et `xml`,
ce qui ralentit le serveur.

Un clone monté depuis l'hôte apporte ses fichiers, pas son git : le `.git`
d'un projet git-repo est un lien relatif vers `.repo/projects`, qui mène au
`.repo` du conteneur lui-même. Odoo charge les modules montés, mais un
instantané lit ce dépôt depuis l'image.

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