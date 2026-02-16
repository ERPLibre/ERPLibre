
# Publication

Un guide sur la generation d'une publication.

## Nettoyer l'environnement avant de generer une nouvelle publication

Avant le nettoyage, verifiez si des fichiers existants ne sont pas commites, pousses ou dans le stash.

```bash
.venv.erplibre/bin/repo forall -pc "git stash list"
./script/git/git_show_code_diff_repo_manifest.py
```

Ceci effacera tout dans les addons. Utile avant de creer un docker, un manifeste et de faire une publication.

```bash
./script/git/clean_repo_manifest.sh
```

Et mettre a jour tout depuis dev pour fusionner dans prod.

Tester toutes les versions Odoo supportees :

```bash
make install_odoo_all_version
```

## Valider l'environnement

- Verifier si chaque version de manifeste comme [manifest/default.dev.odoo16.0.xml](../manifest/default.dev.odoo16.0.xml) est prete pour la production.
- Executer les tests :

```bash
make test_full_fast
```

### Formater le code

Pour formater tout le code, executez :

```bash
make format
```

### Mettre a jour les documentations

Pour generer le Markdown dans le repertoire `./doc`, executez :

```bash
make doc_markdown
```

### Tester la generation docker

Pour generer un docker, executez :

```bash
make docker_build_odoo_18
```

### Renommer l'ancienne version vers la nouvelle version

Rechercher l'ancienne version, comme :

```bash
grep --color=always --exclude-dir={.repo,.venv,.git} --exclude="*.svg" -nri v1.6.0
```

Remplacer si necessaire par la nouvelle version.

Mettre a jour le fichier `./pyproject.toml` dans [tool.poetry], ligne `version =`.

### Tester l'environnement de production Ubuntu

Suivre les instructions dans [PRODUCTION.md](./PRODUCTION.md).

Tester l'installation avec le generateur de code Geomap :

```bash
make addons_install_code_generator_full
```

### Mettre a jour image_db

Pour generer les images de base de donnees dans le repertoire `./image_db`, executez :

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

## Generer la nouvelle production et publication

Generer le manifeste de production et geler toutes les versions des depots.

```bash
.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

Mettre a jour la variable ERPLIBRE_VERSION dans [env_var.sh](../env_var.sh), [Dockerfile.prod](../docker/Dockerfile.prod.pkg)
et [docker-compose](../docker-compose.yml).

Generer [poetry](./POETRY.md) et garder uniquement les dependances manquantes, retirer les mises a jour.

```bash
./script/poetry/poetry_update.py
```

Lors de l'execution du script ./script/poetry/poetry_update.py, noter les dependances inserees manuellement, stasher tous les changements et les ajouter
manuellement.

```bash
poetry add DEPENDENCY
```

Comprendre les differences depuis la derniere publication :

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

Mettre a jour le fichier [CHANGELOG.md](../CHANGELOG.md) et creer une section avec la nouvelle version, utiliser la commande suivante pour lire tous les changements.

Creer une branche release/#.#.# et creer une demande de fusion vers la branche master avec votre commit :

```bash
git commit -am "Release v#.#.#"
```

Faire reviser par vos pairs, tester le fichier docker et **fusionner dans master**.

```bash
git checkout master
git merge --no-ff RELEASE_BRANCH
```

Ajouter le commentaire `Release v#.#.#`.

## Creer le tag

Ajouter un tag sur le commit dans la branche master avec votre publication. Lors de l'ajout du tag, assurez-vous de mettre a jour default.xml

```bash
git tag v#.#.#
# Push your tags
git push --tags
# Add tags for all repo
.venv.erplibre/bin/repo forall -pc "git tag ERPLibre/v#.#.#"
make tag_push_all
```

## Generer et pousser le docker

Important de generer le conteneur apres avoir pousse les tags git, sinon la version git sera incorrecte.

Lors de la construction de votre docker avec le script
> make docker_build_release

Lister votre version docker
> docker images

Vous devez pousser votre image docker et mettre a jour votre tag, comme 1.0.1 :
> docker push technolibre/erplibre:VERSION

## Faire une publication sur github

Visiter `https://github.com/ERPLibre/ERPLibre/releases/new` et creer une publication nommee `v#.#.#` et copier les informations depuis
CHANGELOG.md.

# ASTUCES

## Comparer les differences de depots avec un autre projet ERPLibre

Pour generer une liste de differences entre les commits git des depots

```bash
./script/git/git_change_remote.py --sync_to /path/to/directory
```

## Versionnage semantique

```
<valid semver> ::= <version core> "-" <pre-release> "+" <build>
```
