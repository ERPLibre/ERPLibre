
# À FAIRE

## Installation Deb
devops_erplibre a besoin de sshpass

## Simplifier le push des tags
Pour RELEASE.md, remplacer la valeur suivante par un script pour sélectionner tous les dépôts distants par fichier manifest.
Actuellement, il faut pousser manuellement tous les différents dépôts distants.

> .venv.erplibre/bin/repo forall -pc "git push ERPLibre --tags"

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