
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

Le programme du deck est un projet Google Repo dans
`script/stream_deck/deck/`, que le git d'ERPLibre ignore.
`manifest/git_manifest_erplibre_streamdeck_deck.xml` pointe sur sa branche
`main` : un checkout reçoit le dernier programme du deck à chaque mise à
jour. `script/stream_deck/deck_contract` porte la version du contrat pour
laquelle ERPLibre est écrit, et `test/test_streamdeck_deck_repo.py` échoue
quand la version MAJEURE du `CONTRACT.md` du checkout diffère ou que sa
MINEURE est plus basse : un tel checkout n'a pas tout ce dont ERPLibre se
sert. Les tests d'ERPLibre qui lisent le checkout passent par
`test/streamdeck_deck.py`, et sont sautés, en nommant la commande
d'installation, quand il manque.

Google Repo l'amène de deux façons :

- **La mise à jour des manifestes.** `conf/git_manifest_streamdeck.csv`
  nomme le manifeste, dans le groupe `streamdeck`, à part du groupe
  `erplibre_home` de l'extension : la base d'ERPLibre Home s'installe sans
  le deck. `git_merge_repo_manifest.py` l'ajoute quand
  `script/stream_deck/deck` existe, ou avec `--with_streamdeck` ; un
  serveur Odoo ne le reçoit jamais. Chaque
  `script/manifest/update_manifest_*.sh` le synchronise alors sur `main`.
- **L'installateur**, au niveau Stream Deck :

```
make erplibre_home_streamdeck_install
```

  Comme pour l'extension (voir
  [l'extension dans ERPLibre](erplibre_home_gnome_extension.fr.md)), il
  prend `repo` dans `.venv.erplibre` : `./script/install/install_erplibre.sh`
  passe donc d'abord. Il ajoute le projet du deck à
  `.repo/local_manifests/erplibre_manifest.xml`, sans rien retirer de ce
  fichier, et lance `repo sync` sur ce seul chemin à chaque exécution,
  puis installe son `requirements.txt` dans `.venv.streamdeck`. Une
  installation de la base lancée ensuite garde le deck dans le manifeste
  local. Un répertoire qui n'est pas un checkout repo, un clone git ou une
  copie, est mis de côté entier dans
  `script/stream_deck/deck.avant-repo-<date>/`, nommé dans le bilan, et
  remis en place quand le sync échoue : le répertoire d'où le service
  lance le programme n'est jamais laissé absent ni vide. Sur un checkout
  repo, un sync en échec laisse le programme du deck tel quel, et le bilan
  dit « NOT updated ». `--uninstall` ne retire ni le checkout, ni `.repo`,
  ni le manifeste local.

## Ce qu'ERPLibre en lance

`DECK_PROGRAM` de `streamdeck.conf` choisit ce que lance le service
`erplibre-home-streamdeck.service`, par
`script/install/erplibre_home_deck.sh` : `tiler`, le paquet
`script/stream_deck/deck/erplibre_streamdeck`, ou `controller`,
`script/stream_deck/deck/erplibre_controller.py`, tous deux sous
`.venv.streamdeck`. Sans le checkout, la vérification de démarrage du
service et le point d'entrée s'arrêtent sur une ligne qui nomme
`make erplibre_home_streamdeck_install`. Les cibles make
`streamdeck_erplibre`, `streamdeck`, `streamdeck_tiler`,
`streamdeck_translator_*`, `streamdeck_tiler_unittest` (toute la suite du
deck) et `streamdeck_translator_unittest` lancent un fichier du checkout et
s'arrêtent de même. TODO › ERPLibre Home lit le verrou du deck par le
`deck_lock.py` du checkout, liste les plugins de
`erplibre_streamdeck/plugins/`, et dit « Programme du deck : pas installé »
sans lui. L'extension GNOME cherche le programme du deck d'abord dans
`script/stream_deck/deck/` (son contrat 1.5).

## Modifier le programme du deck

Un commit poussé sur `main` d'erplibre_streamdeck atteint chaque checkout à
sa prochaine mise à jour. Lancer d'abord les tests du deck, dans son
répertoire :

```
cd script/stream_deck/deck
../../../.venv.streamdeck/bin/python -m unittest discover -s tests
git push TechnoLibre HEAD:main
```

`make streamdeck_tiler_unittest`, depuis la racine d'ERPLibre, lance la
même suite. Un changement que l'autre côté voit fait monter la version du
contrat dans `CONTRACT.md`, comme le dit `CONTRACT.md`. Une version MINEURE
ne demande rien d'autre ; la reporter dans `deck_contract` d'ERPLibre dès
qu'ERPLibre se sert de ce qu'elle ajoute, puisqu'un clone en dessous fait
alors échouer les tests d'ERPLibre. Une version MAJEURE fait casser les
checkouts tant qu'ERPLibre ne suit pas : pousser le côté ERPLibre, avec
`deck_contract` à la nouvelle version, en même temps.

`script/stream_deck/deck/` est un projet Google Repo d'erplibre_streamdeck :
son `.git` est un lien vers `.repo/`, et son remote porte le nom de celui
du manifeste, `TechnoLibre`, en https. Travailler sur une branche que lance
`repo start <branche> script/stream_deck/deck`, commiter, et la pousser
(`git push TechnoLibre <branche>` ; pour SSH, régler
`url.git@github.com:.pushInsteadOf https://github.com/` dans la config de
git). Chaque exécution de l'installateur et chaque mise à jour des
manifestes le synchronise selon les règles de repo : une branche lancée par
`repo start` garde ses commits, rebasés sur le nouveau `main` ; un HEAD
détaché passe sur `main` et laisse les commits faits dessus (`git reflog`
les retrouve) ; un sync que repo refuse, des modifications non commitées en
travers ou un conflit de rebase, laisse le checkout tel quel, et
l'installateur dit « NOT updated ». Un programme du deck en marche garde le
code qu'il a chargé : relancer le service
(`systemctl --user restart erplibre-home-streamdeck.service`).
