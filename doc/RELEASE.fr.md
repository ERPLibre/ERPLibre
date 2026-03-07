
# Publication

Un guide sur la génération d'une publication.

## Nettoyer l'environnement avant de générer une nouvelle publication

Avant le nettoyage, vérifiez si des fichiers existants ne sont pas commités, poussés ou dans le stash.

```bash
.venv.erplibre/bin/repo forall -pc "git stash list"
./script/git/git_show_code_diff_repo_manifest.py
```

Ceci effacera tout dans les addons. Utile avant de créer un docker, un manifeste et de faire une publication.

```bash
./script/git/clean_repo_manifest.sh
```

Et mettre à jour tout depuis dev pour fusionner dans prod.

Tester toutes les versions Odoo supportées :

```bash
make install_odoo_all_version
```

## Valider l'environnement

- Vérifier si chaque version de manifeste comme [manifest/default.dev.odoo16.0.xml](../manifest/default.dev.odoo16.0.xml) est prête pour la production.
- Exécuter les tests :

```bash
make test_full_fast
```

### Formater le code

Pour formater tout le code, exécutez :

```bash
make format
```

### Mettre à jour les documentations

Pour générer le Markdown dans le répertoire `./doc`, exécutez :

```bash
make doc_markdown
```

### Tester la génération docker

Pour générer un docker, exécutez :

```bash
make docker_build_odoo_18
```

### Renommer l'ancienne version vers la nouvelle version

Rechercher l'ancienne version, comme :

```bash
grep --color=always --exclude-dir={.repo,.venv,.git} --exclude="*.svg" -nri v1.6.0
```

Remplacer si nécessaire par la nouvelle version.

Mettre à jour le fichier `./pyproject.toml` dans [tool.poetry], ligne `version =`.

### Tester l'environnement de production Ubuntu

Suivre les instructions dans [PRODUCTION.md](./PRODUCTION.md).

Tester l'installation avec le générateur de code Geomap :

```bash
make addons_install_code_generator_full
```

### Mettre à jour image_db

Pour générer les images de base de données dans le répertoire `./image_db`, exécutez :

```bash
make db_clean_cache
make config_gen_all
make image_db_create_all_parallel
```

Pour le tester, vous devez nettoyer les caches et l'installer :

```bash
./script/database/db_restore.py --clean_cache
./script/database/db_restore.py --database test --image erplibre_website
```

## Générer la nouvelle production et publication

Générer le manifeste de production et geler toutes les versions des dépôts.

```bash
.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

Mettre à jour la variable ERPLIBRE_VERSION dans [env_var.sh](../env_var.sh), [Dockerfile.prod](../docker/Dockerfile.prod.pkg)
et [docker-compose](../docker-compose.yml).

Générer [poetry](./POETRY.md) et garder uniquement les dépendances manquantes, retirer les mises à jour.

```bash
./script/poetry/poetry_update.py
```

Lors de l'exécution du script ./script/poetry/poetry_update.py, noter les dépendances insérées manuellement, stasher tous les changements et les ajouter
manuellement.

```bash
poetry add DEPENDENCY
```

Comprendre les différences depuis la dernière publication :

```bash
# Get all differences between the last tag and HEAD, to update the CHANGELOG.md
# ERPLibre
git diff v#.#.#..HEAD

# All repo
.venv.erplibre/bin/repo forall -pc "git diff ERPLibre/v#.#.#..HEAD"
```

Outils de simplification :

```bash
# Show all divergence repository with production
make repo_diff_manifest_production
# Short version with statistics
make repo_diff_stat_from_last_version
# Long version
make repo_diff_from_last_version
```

Mettre à jour le fichier [CHANGELOG.md](../CHANGELOG.md) et créer une section avec la nouvelle version, utiliser la commande suivante pour lire tous les changements.

Créer une branche release/#.#.# et créer une demande de fusion vers la branche master avec votre commit :

```bash
git commit -am "Release v#.#.#"
```

Faire réviser par vos pairs, tester le fichier docker et **fusionner dans master**.

```bash
git checkout master
git merge --no-ff RELEASE_BRANCH
```

Ajouter le commentaire `Release v#.#.#`.

## Créer le tag

Ajouter un tag sur le commit dans la branche master avec votre publication. Lors de l'ajout du tag, assurez-vous de mettre à jour default.xml

```bash
git tag v#.#.#
# Push your tags
git push --tags
# Add tags for all repo
.venv.erplibre/bin/repo forall -pc "git tag ERPLibre/v#.#.#"
make tag_push_all
```

## Générer et pousser le docker

Important de générer le conteneur après avoir poussé les tags git, sinon la version git sera incorrecte.

Lors de la construction de votre docker avec le script
> make docker_build_release

Lister votre version docker
> docker images

Vous devez pousser votre image docker et mettre à jour votre tag, comme 1.0.1 :
> docker push technolibre/erplibre:VERSION

## Faire une publication sur github

Visiter `https://github.com/ERPLibre/ERPLibre/releases/new` et créer une publication nommée `v#.#.#` et copier les informations depuis
CHANGELOG.md.

# ASTUCES

## Comparer les différences de dépôts avec un autre projet ERPLibre

Pour générer une liste de différences entre les commits git des dépôts

```bash
./script/git/git_change_remote.py --sync_to /path/to/directory
```

## Versionnage sémantique

```
<valid semver> ::= <version core> "-" <pre-release> "+" <build>
```