<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# TODO

## Deb installation
devops_erplibre need sshpass

## Simplify push tag
For RELEASE.md, replace next value by a script to select all remote by manifest file.
Actually, need to push manually all different remote.

<!-- [fr] -->
# À FAIRE

## Installation Deb
devops_erplibre a besoin de sshpass

## Simplifier le push des tags
Pour RELEASE.md, remplacer la valeur suivante par un script pour sélectionner tous les dépôts distants par fichier manifest.
Actuellement, il faut pousser manuellement tous les différents dépôts distants.

<!-- [common] -->
> .venv.erplibre/bin/repo forall -pc "git push ERPLibre --tags"

<!-- [en] -->
## Funding
- Add funding for MathBenTech and TechnoLibre

## Improve repo init usage
- Support run repo init without human interaction. Do we need to create a temporary user name?

## Improve repo sync usage
- Test repo sync with argument -d
- Test repo sync with argument -t SMART_TAG, like tag ERPLibre/v1.0.0

## Git diff
### Between 2 commits
- Show all modified file, files list.
- Show if probably has conflict if cherry-pick in wrong order,
- Show modify same line in different commit

## Development
### Run with another address ip than local
- Remove xmlrpc_interface in config file when running dev installation
- Improve config builder with a Python script

### Variable in new instance
- Add technique to add variable when create a new instance from config files
- Documentation for adding mail server, a guide for every one

<!-- [fr] -->
## Financement
- Ajouter du financement pour MathBenTech et TechnoLibre

## Améliorer l'utilisation de repo init
- Supporter l'exécution de repo init sans interaction humaine. Faut-il créer un nom d'utilisateur temporaire ?

## Améliorer l'utilisation de repo sync
- Tester repo sync avec l'argument -d
- Tester repo sync avec l'argument -t SMART_TAG, comme le tag ERPLibre/v1.0.0

## Git diff
### Entre 2 commits
- Afficher tous les fichiers modifiés, liste des fichiers.
- Montrer s'il y a probablement un conflit si le cherry-pick est dans le mauvais ordre,
- Montrer les modifications sur la même ligne dans différents commits

## Développement
### Exécuter avec une autre adresse IP que locale
- Supprimer xmlrpc_interface dans le fichier de configuration lors de l'installation dev
- Améliorer le constructeur de configuration avec un script Python

### Variable dans une nouvelle instance
- Ajouter une technique pour ajouter des variables lors de la création d'une nouvelle instance depuis les fichiers de configuration
- Documentation pour ajouter un serveur de messagerie, un guide pour tout le monde
