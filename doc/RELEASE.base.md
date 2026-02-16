<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Release

A guide on how to generate a release.

<!-- [fr] -->
# Publication

Un guide sur la generation d'une publication.

<!-- [en] -->
## Clean environment before generating new release

Before the cleaning, check if existing file isn't committed, not pushed or in stash.

<!-- [fr] -->
## Nettoyer l'environnement avant de generer une nouvelle publication

Avant le nettoyage, verifiez si des fichiers existants ne sont pas commites, pousses ou dans le stash.

<!-- [common] -->
```bash
.venv.erplibre/bin/repo forall -pc "git stash list"
./script/git/git_show_code_diff_repo_manifest.py
```

<!-- [en] -->
This will erase everything in addons. Useful before creating docker, manifest and do a release.

<!-- [fr] -->
Ceci effacera tout dans les addons. Utile avant de creer un docker, un manifeste et de faire une publication.

<!-- [common] -->
```bash
./script/git/clean_repo_manifest.sh
```

<!-- [en] -->
And update all from dev to merge into prod.

Test all supported Odoo version :

<!-- [fr] -->
Et mettre a jour tout depuis dev pour fusionner dans prod.

Tester toutes les versions Odoo supportees :

<!-- [common] -->
```bash
make install_odoo_all_version
```

<!-- [en] -->
## Validate environment

- Check if each manifest version like [manifest/default.dev.odoo16.0.xml](../manifest/default.dev.odoo16.0.xml) is ready for production.
- Run test :

<!-- [fr] -->
## Valider l'environnement

- Verifier si chaque version de manifeste comme [manifest/default.dev.odoo16.0.xml](../manifest/default.dev.odoo16.0.xml) est prete pour la production.
- Executer les tests :

<!-- [common] -->
```bash
make test_full_fast
```

<!-- [en] -->
### Format code

To format all code, run:

<!-- [fr] -->
### Formater le code

Pour formater tout le code, executez :

<!-- [common] -->
```bash
make format
```

<!-- [en] -->
### Update documentations

To generate Markdown in directory `./doc`, run:

<!-- [fr] -->
### Mettre a jour les documentations

Pour generer le Markdown dans le repertoire `./doc`, executez :

<!-- [common] -->
```bash
make doc_markdown
```

<!-- [en] -->
### Test docker generate

To generate a docker, run:

<!-- [fr] -->
### Tester la generation docker

Pour generer un docker, executez :

<!-- [common] -->
```bash
make docker_build_odoo_18
```

<!-- [en] -->
### Rename old version to new version

Search old version, like :

<!-- [fr] -->
### Renommer l'ancienne version vers la nouvelle version

Rechercher l'ancienne version, comme :

<!-- [common] -->
```bash
grep --color=always --exclude-dir={.repo,.venv,.git} --exclude="*.svg" -nri v1.6.0
```

<!-- [en] -->
Replace if need it to new version.

Update file `./pyproject.toml` in [tool.poetry], line `version =`.

<!-- [fr] -->
Remplacer si necessaire par la nouvelle version.

Mettre a jour le fichier `./pyproject.toml` dans [tool.poetry], ligne `version =`.

<!-- [en] -->
### Test production Ubuntu environment

Follow instructions in [PRODUCTION.md](./PRODUCTION.md).

Test installation with code generator Geomap:

<!-- [fr] -->
### Tester l'environnement de production Ubuntu

Suivre les instructions dans [PRODUCTION.md](./PRODUCTION.md).

Tester l'installation avec le generateur de code Geomap :

<!-- [common] -->
```bash
make addons_install_code_generator_full
```

<!-- [en] -->
### Update image_db

To generate database images in directory `./image_db`, run:

<!-- [fr] -->
### Mettre a jour image_db

Pour generer les images de base de donnees dans le repertoire `./image_db`, executez :

<!-- [common] -->
```bash
make db_clean_cache
make config_gen_all
make image_db_create_all_parallel
```

<!-- [en] -->
To test it, you need to clean caches and install it:

<!-- [fr] -->
Pour le tester, vous devez nettoyer les caches et l'installer :

<!-- [common] -->
```bash
./script/database/db_restore.py --clean_cache
./script/database/db_restore.py --database test --image erplibre_website
```

<!-- [en] -->
## Generate new prod and release

Generate production manifest and freeze all repos versions.

<!-- [fr] -->
## Generer la nouvelle production et publication

Generer le manifeste de production et geler toutes les versions des depots.

<!-- [common] -->
```bash
.venv.erplibre/bin/repo manifest -r -o ./default.xml
```

<!-- [en] -->
Update ERPLIBRE_VERSION variable in [env_var.sh](../env_var.sh), [Dockerfile.prod](../docker/Dockerfile.prod.pkg)
and [docker-compose](../docker-compose.yml).

Generate [poetry](./POETRY.md) and keep only missing dependencies, remove updates.

<!-- [fr] -->
Mettre a jour la variable ERPLIBRE_VERSION dans [env_var.sh](../env_var.sh), [Dockerfile.prod](../docker/Dockerfile.prod.pkg)
et [docker-compose](../docker-compose.yml).

Generer [poetry](./POETRY.md) et garder uniquement les dependances manquantes, retirer les mises a jour.

<!-- [common] -->
```bash
./script/poetry/poetry_update.py
```

<!-- [en] -->
When running script ./script/poetry/poetry_update.py, note manually inserted dependencies, stash all changes and add it
manually.

<!-- [fr] -->
Lors de l'execution du script ./script/poetry/poetry_update.py, noter les dependances inserees manuellement, stasher tous les changements et les ajouter
manuellement.

<!-- [common] -->
```bash
poetry add DEPENDENCY
```

<!-- [en] -->
Understand differences from last release:

<!-- [fr] -->
Comprendre les differences depuis la derniere publication :

<!-- [common] -->
```bash
# Get all differences between the last tag and HEAD, to update the CHANGELOG.md
# ERPLibre
git diff v#.#.#..HEAD

# All repo
.venv.erplibre/bin/repo forall -pc "git diff ERPLibre/v#.#.#..HEAD"
```

<!-- [en] -->
Simplification tools:

<!-- [fr] -->
Outils de simplification :

<!-- [common] -->
```bash
# Show all divergence repository with production
make repo_diff_manifest_production
# Short version with statistics
make repo_diff_stat_from_last_version
# Long version
make repo_diff_from_last_version
```

<!-- [en] -->
Update file [CHANGELOG.md](../CHANGELOG.md) and create a section with new version, use next command to read all changes.

Create a branch release/#.#.# and create a pull request to branch master with your commit:

<!-- [fr] -->
Mettre a jour le fichier [CHANGELOG.md](../CHANGELOG.md) et creer une section avec la nouvelle version, utiliser la commande suivante pour lire tous les changements.

Creer une branche release/#.#.# et creer une demande de fusion vers la branche master avec votre commit :

<!-- [common] -->
```bash
git commit -am "Release v#.#.#"
```

<!-- [en] -->
Review by your peers, test the docker file and **merge to master**.

<!-- [fr] -->
Faire reviser par vos pairs, tester le fichier docker et **fusionner dans master**.

<!-- [common] -->
```bash
git checkout master
git merge --no-ff RELEASE_BRANCH
```

<!-- [en] -->
Add comment `Release v#.#.#`.

<!-- [fr] -->
Ajouter le commentaire `Release v#.#.#`.

<!-- [en] -->
## Create tag

Add a tag on the commit in branch master with your release. When adding tag, be sure to update default.xml

<!-- [fr] -->
## Creer le tag

Ajouter un tag sur le commit dans la branche master avec votre publication. Lors de l'ajout du tag, assurez-vous de mettre a jour default.xml

<!-- [common] -->
```bash
git tag v#.#.#
# Push your tags
git push --tags
# Add tags for all repo
.venv.erplibre/bin/repo forall -pc "git tag ERPLibre/v#.#.#"
make tag_push_all
```

<!-- [en] -->
## Generate and push docker

Important to generate container after push git tags, otherwise the git version will be wrong.

When building your docker with script
> make docker_build_release

List your docker version
> docker images

You need to push your docker image and update your tag, like 1.0.1:
> docker push technolibre/erplibre:VERSION

<!-- [fr] -->
## Generer et pousser le docker

Important de generer le conteneur apres avoir pousse les tags git, sinon la version git sera incorrecte.

Lors de la construction de votre docker avec le script
> make docker_build_release

Lister votre version docker
> docker images

Vous devez pousser votre image docker et mettre a jour votre tag, comme 1.0.1 :
> docker push technolibre/erplibre:VERSION

<!-- [en] -->
## Do a release on github

Visit `https://github.com/ERPLibre/ERPLibre/releases/new` and create a release named `v#.#.#` and copy information from
CHANGELOG.md.

<!-- [fr] -->
## Faire une publication sur github

Visiter `https://github.com/ERPLibre/ERPLibre/releases/new` et creer une publication nommee `v#.#.#` et copier les informations depuis
CHANGELOG.md.

<!-- [en] -->
# TIPS

## Compare repo differences with another ERPLibre project

To generate a list of differences between repo git commit

<!-- [fr] -->
# ASTUCES

## Comparer les differences de depots avec un autre projet ERPLibre

Pour generer une liste de differences entre les commits git des depots

<!-- [common] -->
```bash
./script/git/git_change_remote.py --sync_to /path/to/directory
```

<!-- [en] -->
## Semantic versioning

<!-- [fr] -->
## Versionnage semantique

<!-- [common] -->
```
<valid semver> ::= <version core> "-" <pre-release> "+" <build>
```
