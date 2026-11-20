
# Le programme du deck Stream Deck dans ERPLibre

Le programme du deck d'ERPLibre Home forme un dépôt à part,
[erplibre_streamdeck](https://github.com/TechnoLibre/erplibre_streamdeck) :
le paquet `erplibre_streamdeck` et ses plugins, le contrôleur classique
`erplibre_controller.py`, le verrou du deck `deck_lock.py`, le traducteur
parole-texte, `requirements.txt` et ses tests. Il tourne sans ERPLibre ;
son `README.md` dit comment. Cette page couvre ce qu'ERPLibre ajoute : où
vit le programme du deck dans un checkout, comment il arrive et suit les
nouveaux commits, ce qu'ERPLibre en lance, et comment le modifier.
`CONTRACT.md`, à la racine du dépôt du deck, dit ce que chaque côté attend
de l'autre.

## Dans un checkout

Le programme du deck est cloné dans `script/stream_deck/deck/`, que le git
d'ERPLibre ignore. `manifest/git_manifest_erplibre_streamdeck_deck.xml`
pointe sur sa branche `main` : un checkout reçoit le dernier programme du
deck à chaque mise à jour. `script/stream_deck/deck_contract` porte la
version du contrat pour laquelle ERPLibre est écrit, et
`test/test_streamdeck_deck_repo.py` échoue quand la version MAJEURE du
`CONTRACT.md` du clone diffère ou que sa MINEURE est plus basse : un tel
clone n'a pas tout ce dont ERPLibre se sert. Les tests d'ERPLibre qui
lisent le clone passent par `test/streamdeck_deck.py`, et sont sautés, en
nommant la commande d'installation, quand le clone manque.

Il arrive de deux façons :

- **Google Repo.** `conf/git_manifest_streamdeck.csv` nomme le manifeste,
  dans le groupe `streamdeck`, à part du groupe `erplibre_home` de
  l'extension : la base d'ERPLibre Home s'installe sans le deck.
  `git_merge_repo_manifest.py` l'ajoute quand `script/stream_deck/deck`
  existe, ou avec `--with_streamdeck` ; un serveur Odoo ne le clone jamais.
  Chaque `script/manifest/update_manifest_*.sh` le synchronise alors sur
  `main`. `repo sync` refuse un clone ordinaire fait par l'installateur :
  `script/manifest/streamdeck_deck_to_repo.sh`, lancé entre `repo init` et
  `repo sync`, ne déplace que son `.git` vers
  `script/stream_deck/deck.plain-clone-git-<date>/` quand il ne porte aucun
  travail local, et repo extrait `main` par-dessus les fichiers en place :
  le répertoire d'où le service lance le programme n'est jamais vide. Il
  arrête sinon la mise à jour en nommant ce travail, et aussi quand l'init
  ferait supprimer le deck par repo (groupe `streamdeck` absent de
  `repo init -g`).
- **L'installateur**, pour un checkout sans Google Repo, au niveau Stream
  Deck :

```
make erplibre_home_streamdeck_install
```

  Il clone le programme du deck quand son répertoire manque ou ne garde que
  des caches Python, en HEAD détaché sur le dernier commit de `main`, puis
  installe son `requirements.txt` dans `.venv.streamdeck`. À chaque
  exécution suivante, il va chercher `main` et amène un clone qu'il a fait
  à son nouveau dernier commit ; une branche ou du travail local reste, et
  le bilan le dit. Tout autre contenu arrête l'installation en le nommant.
  `--uninstall` ne retire jamais le clone.

## Ce qu'ERPLibre en lance

`DECK_PROGRAM` de `streamdeck.conf` choisit ce que lance le service
`erplibre-home-streamdeck.service`, par
`script/install/erplibre_home_deck.sh` : `tiler`, le paquet
`script/stream_deck/deck/erplibre_streamdeck`, ou `controller`,
`script/stream_deck/deck/erplibre_controller.py`, tous deux sous
`.venv.streamdeck`. Sans le clone, la vérification de démarrage du service
et le point d'entrée s'arrêtent sur une ligne qui nomme
`make erplibre_home_streamdeck_install`. Les cibles make
`streamdeck_erplibre`, `streamdeck`, `streamdeck_tiler`,
`streamdeck_translator_*`, `streamdeck_tiler_unittest` (toute la suite du
deck) et `streamdeck_translator_unittest` lancent un fichier du clone et
s'arrêtent de même. TODO › ERPLibre Home lit le verrou du deck par le
`deck_lock.py` du clone, liste les plugins de `erplibre_streamdeck/plugins/`,
et dit « Programme du deck : pas cloné » sans lui. L'extension GNOME
cherche le programme du deck d'abord dans le clone (son contrat 1.5).

## Modifier le programme du deck

Un commit poussé sur `main` d'erplibre_streamdeck atteint chaque checkout à
sa prochaine mise à jour. Lancer d'abord les tests du deck, dans son
répertoire :

```
cd script/stream_deck/deck
../../../.venv.streamdeck/bin/python -m unittest discover -s tests
git push origin main
```

`make streamdeck_tiler_unittest`, depuis la racine d'ERPLibre, lance la
même suite. Un changement que l'autre côté voit fait monter la version du
contrat dans `CONTRACT.md`, comme le dit `CONTRACT.md`. Une version MINEURE
ne demande rien d'autre ; la reporter dans `deck_contract` d'ERPLibre dès
qu'ERPLibre se sert de ce qu'elle ajoute, puisqu'un clone en dessous fait
alors échouer les tests d'ERPLibre. Une version MAJEURE fait casser les
checkouts tant qu'ERPLibre ne suit pas : pousser le côté ERPLibre, avec
`deck_contract` à la nouvelle version, en même temps.

`script/stream_deck/deck/` est un checkout git d'erplibre_streamdeck. Un
clone fait par l'installateur est détaché sur un commit de `main` et nomme
son remote `origin` ; un projet Google Repo le nomme d'après le remote du
manifeste, `TechnoLibre`. Partir d'une branche sur le `main` du remote
(`git fetch origin main` puis `git switch -c <branche> FETCH_HEAD`, avec
`TechnoLibre` pour un projet repo), commiter, et la pousser. Tant que le
clone est sur une branche ou porte du travail local, l'installateur le
laisse ; tant qu'il porte du travail local, une mise à jour des manifestes
s'arrête avant d'y toucher. Un programme du deck en marche garde le code
qu'il a chargé : relancer le service
(`systemctl --user restart erplibre-home-streamdeck.service`).
