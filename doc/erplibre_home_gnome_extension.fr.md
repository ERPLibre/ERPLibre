
# L'extension GNOME ERPLibre Home dans ERPLibre

L'extension GNOME ERPLibre Home forme un dépôt à part,
[erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension),
qui tourne sans ERPLibre ; son `README.md` dit comment. Cette page couvre
ce qu'ERPLibre ajoute : où vit l'extension dans un checkout, comment elle
arrive et suit les nouveaux commits, ce qu'ERPLibre en lance, et comment la
modifier. `CONTRACT.md`, à la racine de l'extension, dit ce que chaque côté
attend de l'autre.

## Dans un checkout

L'extension est un projet Google Repo dans
`script/gnome-extension/erplibre_home/`, que le git d'ERPLibre ignore, et
elle est liée en
`~/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca`.
`manifest/git_manifest_erplibre_home_gnome_extension.xml` pointe sur sa
branche `main` : un checkout reçoit la dernière extension à chaque mise à
jour. `script/gnome-extension/erplibre_home_contract` porte la version du
contrat pour laquelle ERPLibre est écrit, et
`test/test_erplibre_home_extension_repo.py` échoue quand la version
MAJEURE du checkout diffère. Les tests d'ERPLibre ne lisent du checkout que
ce qu'énonce son `CONTRACT.md`, avec les valeurs qu'il donne
(`test/erplibre_home_extension.py`) : le code de l'extension peut changer
de forme tant que ses propres tests le tiennent au contrat.

Google Repo l'amène de deux façons :

- **La mise à jour des manifestes.** `conf/git_manifest_erplibre_home.csv`
  nomme le manifeste, dans le groupe `erplibre_home`, à part de celui du
  Stream Deck : la base s'installe sans le deck.
  `git_merge_repo_manifest.py` l'ajoute quand
  `script/gnome-extension/erplibre_home` existe, ou avec
  `--with_erplibre_home` ; un serveur Odoo ne la reçoit jamais. Chaque
  `script/manifest/update_manifest_*.sh` la synchronise alors sur `main`.
- **L'installateur**, aux deux niveaux :

```
make erplibre_home_install
```

  Il prend `repo` dans `.venv.erplibre` :
  `./script/install/install_erplibre.sh` passe donc d'abord
  (`./script/install/install_git_repo.sh` ajoute `bin/repo` quand seul
  celui-ci manque). Un checkout sans `.repo` reçoit un seul `repo init
  --standalone-manifest`, jamais un second. L'installateur ajoute le
  projet de l'extension à `.repo/local_manifests/erplibre_manifest.xml`,
  sans rien retirer de ce fichier, puis lance `repo sync` sur ce seul
  chemin, à chaque exécution, avant de lire les versions de GNOME que
  `metadata.json` prend en charge. Un répertoire qui n'est pas un checkout
  repo, un clone git ou une copie, est mis de côté entier dans
  `script/gnome-extension/erplibre_home.avant-repo-<date>/`, nommé dans le
  bilan, et remis en place quand le sync échoue : le répertoire que charge
  la session n'est jamais laissé absent ni vide. Sur un checkout repo, un
  sync en échec laisse l'extension telle quelle, et le bilan dit « NOT
  updated ». L'installateur s'arrête avant tout sync quand un changement
  de manifeste en attente ferait supprimer un projet par repo : `make`
  passe alors d'abord. La base demande donc `git`, `.venv.erplibre` et
  GitHub ; `--extension-only` (`make erplibre_home_install_extension`)
  synchronise aussi, et `--uninstall` ne retire ni le checkout, ni
  `.repo`, ni le manifeste local.

## Ce qu'ERPLibre en lance

L'installateur lie le checkout, lance `tools/migrate_legacy.py`, compile
`schemas/` et chaque `po/<langue>.po`, et active l'extension par
`tools/enable_next_login.py`. Les cibles make
`erplibre_home_enable_extension`, `erplibre_home_dev_nested`,
`erplibre_home_e2e_nested`, `erplibre_home_compile_locale`,
`extension_i18n_compile`, `claude_install_hooks` et `test_gnome_extension`
lancent un de ses fichiers : sans le checkout, chacune s'arrête sur une
ligne qui nomme `make erplibre_home_install_extension`, qui la synchronise
sans demander GNOME Shell. `make test_full_fast` lance les suites de
l'extension quand le checkout est là, et les annonce sautées sinon. Le
programme du Stream Deck, le contrôleur et le traducteur, un projet Google
Repo à part dans `script/stream_deck/deck/` (voir
[le programme du deck dans ERPLibre](erplibre_streamdeck_deck.fr.md)), et le
menu TODO parlent à l'extension en marche par D-Bus et se dégradent quand
elle ne répond pas. L'extension, elle, trouve le checkout d'ERPLibre par
son propre chemin et lance le programme du deck et le contrôleur depuis
`script/stream_deck/deck/`, ou depuis `script/stream_deck/` dans un
checkout d'ERPLibre antérieur au dépôt propre du deck (contrat 1.5).

## Les commits d'ERPLibre plus anciens

Les commits d'ERPLibre antérieurs au passage de l'extension dans son propre
dépôt suivent ses fichiers à ce même chemin, comme les branches faites à
partir d'eux. git tient les fichiers qu'il ignore pour jetables : extraire
une telle branche ou un tel commit écrit ses versions par-dessus les
fichiers du clone sans rien demander, et les modifications non commitées de
l'extension sont perdues. Extraire de nouveau un commit plus récent
supprime ces fichiers, et le répertoire que charge la session ne garde que
`.git` et ce que le clone ne suit pas. Un bisect qui traverse ce passage
fait de même.

Travailler sur une telle branche dans son propre worktree, `git worktree
add <répertoire> <branche>`, et y fusionner la branche courante ; une fois
fusionnée, elle ne suit plus l'extension. Quand c'est arrivé, restaurer les
fichiers du clone depuis son propre historique :

```
git -C script/gnome-extension/erplibre_home checkout -- .
```

Le hook `post-checkout` de `script/git/hooks` (`git config core.hooksPath
script/git/hooks`) affiche cette commande après une extraction depuis ou
vers un commit qui suit l'extension. Il ne restaure rien lui-même : il ne
distingue pas un écrasement d'une modification voulue.

## Modifier l'extension

Un commit poussé sur `main` d'erplibre-home-gnome-extension atteint chaque
checkout à sa prochaine mise à jour. Lancer d'abord les tests de
l'extension, dans son répertoire :

```
node --test test/unit/*.test.js
python3 -m unittest discover -s test/python
git push TechnoLibre HEAD:main
```

`make test_gnome_extension`, depuis la racine d'ERPLibre, lance les mêmes
suites après une vérification stricte du schéma. Un changement que l'autre
côté voit fait monter la version du contrat dans `CONTRACT.md`, comme le
dit `CONTRACT.md`. Une version MINEURE ne demande rien d'autre ; la
reporter dans `erplibre_home_contract` d'ERPLibre quand c'est commode. Une
version MAJEURE fait casser les checkouts tant qu'ERPLibre ne suit pas :
pousser le côté ERPLibre, avec `erplibre_home_contract` à la nouvelle
version, en même temps.

`script/gnome-extension/erplibre_home/` est un projet Google Repo
d'erplibre-home-gnome-extension : son `.git` est un lien vers `.repo/`, et
son remote porte le nom de celui du manifeste, `TechnoLibre`, en https.
Travailler sur une branche que lance `repo start <branche>
script/gnome-extension/erplibre_home`, commiter, et la pousser
(`git push TechnoLibre <branche>` ; pour SSH, régler
`url.git@github.com:.pushInsteadOf https://github.com/` dans la config de
git). Chaque exécution de l'installateur et chaque mise à jour des
manifestes la synchronise selon les règles de repo : une branche lancée
par `repo start` garde ses commits, rebasés sur le nouveau `main` ; un HEAD
détaché passe sur `main` et laisse les commits faits dessus (`git reflog`
les retrouve) ; un sync que repo refuse, des modifications non commitées en
travers ou un conflit de rebase, laisse le checkout tel quel, et
l'installateur dit « NOT updated ». La session GNOME en cours garde le code
qu'elle a chargé : `make erplibre_home_reload` charge une nouvelle copie
sous Wayland sans fermer la session.
