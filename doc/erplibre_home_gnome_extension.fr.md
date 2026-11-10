
# L'extension GNOME ERPLibre Home dans ERPLibre

L'extension GNOME ERPLibre Home forme un dépôt à part,
[erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension),
qui tourne sans ERPLibre ; son `README.md` dit comment. Cette page couvre
ce qu'ERPLibre ajoute : où vit l'extension dans un checkout, comment elle
arrive et suit les nouveaux commits, ce qu'ERPLibre en lance, et comment la
modifier. `CONTRACT.md`, à la racine de l'extension, dit ce que chaque côté
attend de l'autre.

## Dans un checkout

L'extension est clonée dans `script/gnome-extension/erplibre_home/`, que le
git d'ERPLibre ignore, et liée en
`~/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca`.
`manifest/git_manifest_erplibre_home_gnome_extension.xml` pointe sur sa
branche `main` : un checkout reçoit la dernière extension à chaque mise à
jour. `script/gnome-extension/erplibre_home_contract` porte la version du
contrat pour laquelle ERPLibre est écrit, et
`test/test_erplibre_home_extension_repo.py` échoue quand la version
MAJEURE du clone diffère. Les tests d'ERPLibre ne lisent du clone que ce
qu'énonce son `CONTRACT.md`, avec les valeurs qu'il donne
(`test/erplibre_home_extension.py`) : le code de l'extension peut changer
de forme tant que ses propres tests le tiennent au contrat.

Elle arrive de deux façons :

- **Google Repo.** `conf/git_manifest_erplibre_home.csv` nomme le
  manifeste, dans le groupe `erplibre_home`, à part de celui du Stream
  Deck : la base s'installe sans le deck. `git_merge_repo_manifest.py`
  l'ajoute quand `script/gnome-extension/erplibre_home` existe, ou avec
  `--with_erplibre_home` ; un serveur Odoo ne la clone jamais. Chaque
  `script/manifest/update_manifest_*.sh` la synchronise alors sur `main`.
  `repo sync` refuse un clone ordinaire fait par l'installateur :
  `script/manifest/erplibre_home_extension_to_repo.sh`, lancé entre
  `repo init` et `repo sync`, ne déplace que son `.git` vers
  `script/gnome-extension/erplibre_home.plain-clone-git-<date>/` quand il
  ne porte aucun travail local (un clone que git ne lit pas compte comme
  en portant), et repo extrait `main` par-dessus les
  fichiers en place : le répertoire que charge la session n'est jamais
  vide. Il arrête sinon la mise à jour en nommant ce travail, et aussi
  quand l'init ferait supprimer l'extension par repo (groupe
  `erplibre_home` absent de `repo init -g`).
- **L'installateur**, pour un checkout sans Google Repo, aux deux
  niveaux :

```
make erplibre_home_install
```

  Il clone l'extension quand son répertoire manque ou ne garde que ce
  qu'une mise à jour qui cesse de la suivre laisse (`locale/`,
  `schemas/gschemas.compiled`, `__pycache__/`), en HEAD détaché sur le
  dernier commit de `main`, avant de lire les versions de GNOME que
  `metadata.json` prend en charge. À chaque exécution suivante, il va
  chercher `main` et amène un clone qu'il a fait à son nouveau dernier
  commit ; une branche ou du travail local reste, et le bilan le dit. Tout
  autre contenu arrête l'installation en le nommant. La base demande donc
  `git` et GitHub ; `--extension-only` (`make
  erplibre_home_install_extension`) clone aussi, et `--uninstall` ne retire
  jamais le clone.

## Ce qu'ERPLibre en lance

L'installateur lie le clone, lance `tools/migrate_legacy.py`, compile
`schemas/` et chaque `po/<langue>.po`, et active l'extension par
`tools/enable_next_login.py`. Les cibles make
`erplibre_home_enable_extension`, `erplibre_home_dev_nested`,
`erplibre_home_e2e_nested`, `erplibre_home_compile_locale`,
`extension_i18n_compile`, `claude_install_hooks` et `test_gnome_extension`
lancent un de ses fichiers : sans le clone, chacune s'arrête sur une ligne
qui nomme `make erplibre_home_install`. Le programme du Stream Deck, le
contrôleur, le traducteur et le menu TODO parlent à l'extension en marche
par D-Bus et se dégradent quand elle ne répond pas. L'extension, elle,
trouve le checkout par son propre chemin et y lance le programme du deck,
le contrôleur et la galerie des jeux.

## Modifier l'extension

Un commit poussé sur `main` d'erplibre-home-gnome-extension atteint chaque
checkout à sa prochaine mise à jour. Lancer d'abord les tests de
l'extension, dans son répertoire :

```
node --test test/unit/*.test.js
python3 -m unittest discover -s test/python
git push origin main
```

`make test_gnome_extension`, depuis la racine d'ERPLibre, lance les mêmes
suites après une vérification stricte du schéma. Un changement que l'autre
côté voit fait monter la version du contrat dans `CONTRACT.md`, comme le
dit `CONTRACT.md`. Une version MINEURE ne demande rien d'autre ; la
reporter dans `erplibre_home_contract` d'ERPLibre quand c'est commode. Une
version MAJEURE fait casser les checkouts tant qu'ERPLibre ne suit pas :
pousser le côté ERPLibre, avec `erplibre_home_contract` à la nouvelle
version, en même temps.

`script/gnome-extension/erplibre_home/` est un checkout git
d'erplibre-home-gnome-extension. Un clone fait par l'installateur est
détaché sur un commit de `main` et nomme son remote `origin` ; un projet
Google Repo le nomme d'après le remote du manifeste, `TechnoLibre`. Partir
d'une branche sur le `main` du remote (`git fetch origin main` puis
`git switch -c <branche> FETCH_HEAD`, avec `TechnoLibre` pour un projet
repo), commiter, et la pousser. Tant que le clone est sur une branche ou
porte du travail local, l'installateur le laisse ; tant qu'il porte du
travail local, une mise à jour des manifestes s'arrête avant d'y toucher. La session GNOME en cours garde le
code qu'elle a chargé : `make erplibre_home_reload` charge une nouvelle
copie sous Wayland sans fermer la session.
