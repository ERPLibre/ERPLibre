
# Les jeux Stream Deck dans ERPLibre

Les jeux Stream Deck et leur galerie forment un dépôt à part,
[streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), qui
tourne sans ERPLibre ; son `README.md` dit comment. Cette page couvre ce
qu'ERPLibre ajoute : où vivent les jeux dans un checkout, comment ils
arrivent et suivent les nouveaux commits, comment ERPLibre les lance, et
comment les modifier. `CONTRACT.md`, à la racine des jeux, dit ce que chaque
côté attend de l'autre.

## Dans un checkout

Les jeux sont clonés dans `script/stream_deck/games/`, que le git
d'ERPLibre ignore. `manifest/git_manifest_streamdeck_game.xml` pointe sur
leur branche `main` : un checkout reçoit les derniers jeux à chaque mise à
jour. `script/stream_deck/games_contract` porte la version du contrat pour
laquelle ERPLibre est écrit, et `test/test_streamdeck_games_repo.py` échoue
quand la version MAJEURE du clone diffère.

Ils arrivent de deux façons :

- **Google Repo.** `conf/git_manifest_streamdeck.csv` nomme le manifeste.
  Comme la liste du mobile, `git_merge_repo_manifest.py` l'ajoute quand
  `script/stream_deck/games` existe, ou avec `--with_streamdeck` ; un
  serveur Odoo ne clone jamais les jeux. Chaque
  `script/manifest/update_manifest_*.sh` les synchronise alors sur
  `main`. `repo sync` refuse un clone ordinaire fait par
  l'installateur : `script/manifest/streamdeck_games_to_repo.sh`, lancé
  entre `repo init` et `repo sync`, le déplace vers
  `script/stream_deck/games.plain-clone-<date>/` quand il ne porte aucun
  travail local, et arrête sinon la mise à jour en nommant ce travail.
- **L'installateur**, pour un checkout sans Google Repo :

```
make erplibre_home_streamdeck_install
```

  Il clone les jeux quand `games/` manque ou ne garde que `save/` et
  `__pycache__/`, en HEAD détaché sur le dernier commit de `main`. À chaque
  exécution suivante, il va chercher `main` et amène un clone qu'il a fait
  à son nouveau dernier commit ; une branche ou du travail local reste, et
  le bilan le dit, comme il dit un fetch qui échoue. Il installe ensuite
  `script/stream_deck/requirements.txt` et le `requirements.txt` des jeux
  dans `.venv.streamdeck`. `--uninstall` ne retire jamais les jeux.

## Les lancer

TODO › Stream Deck › Jeux et la galerie (`make streamdeck_gallery`, ou le
sous-menu Jeux de l'extension GNOME, qui passe par elle) lancent un jeu
sous `.venv.streamdeck` par `script/install/erplibre_home_handover.sh` : il
tient le verrou du deck, arrête le service du deck le temps du jeu et le
relance après, et refuse (code 4) quand le réglage `GAMES` est à off.
`make streamdeck_<id>`, une cible par jeu dans
`conf/make.streamdeck.Makefile`, lance le jeu directement sous
`.venv.streamdeck`, sans la passation : elle refuse quand `GAMES` est à
off, mais ne prend pas le verrou du deck et n'arrête pas le service ;
arrête donc le service d'abord. Sans les jeux, chaque entrée affiche une
ligne qui nomme `make erplibre_home_streamdeck_install`, et la passation
sort en 5 avant d'arrêter quoi que ce soit ; le programme du deck, le
contrôleur et le service n'ont pas besoin des jeux.

La galerie n'écoute que sur 127.0.0.1:8042. Ses routes qui agissent
(lancer, arrêter, effacer des sauvegardes) n'acceptent qu'une requête
portant l'en-tête `X-Stream-Deck-Gallery: 1`, que sa page et l'extension
GNOME envoient : la page d'un autre site, un lien ou un moteur de rendu de
documents ne peut ni lancer un jeu ni effacer de sauvegarde par elle.

## Sauvegardes

Les jeux gardent leurs sauvegardes dans
`$XDG_DATA_HOME/erplibre-home/streamdeck/save/` (`~/.local/share` par
défaut), hors des deux dépôts : aucun clone, aucune synchronisation, aucun
`git clean` ne les atteint. Celles que d'anciennes versions ont laissées
dans `script/stream_deck/games/save/` y passent à la prochaine exécution.

## Modifier les jeux

Un commit poussé sur `main` de streamdeck_game atteint chaque checkout à sa
prochaine mise à jour. Lancer d'abord les tests des jeux :

```
python3 -m unittest discover -s tests
git push origin main
```

Un changement que l'autre côté voit fait monter la version du contrat dans
`CONTRACT.md` et `games_cli.CONTRACT_VERSION`, comme le dit `CONTRACT.md`.
Une version MINEURE ne demande rien d'autre ; la reporter dans
`games_contract` d'ERPLibre quand c'est commode. Une version MAJEURE fait
casser les checkouts tant qu'ERPLibre ne suit pas : pousser le côté
ERPLibre, avec `games_contract` à la nouvelle version, en même temps. Un nouveau jeu demande aussi sa cible make dans
`conf/make.streamdeck.Makefile`, que réclame
`test_the_game_targets_are_the_games_of_the_clone`.

`script/stream_deck/games/` est un checkout git de streamdeck_game, détaché
sur un commit de `main`. Un clone fait par l'installateur nomme son remote
`origin` ; un projet Google Repo le nomme d'après le remote du manifeste,
`TechnoLibre`. Partir d'une branche sur le `main` du remote
(`git fetch origin main` puis `git switch -c <branche> FETCH_HEAD`, avec
`TechnoLibre` pour un projet repo), commiter, et la pousser vers
streamdeck_game. Tant qu'un clone de l'installateur est sur une branche ou
porte du travail local, l'installateur le laisse et une mise à jour des
manifestes s'arrête avant d'y toucher.
