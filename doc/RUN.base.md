<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Execute ERPLibre

## Start database

<!-- [fr] -->
# Exécuter ERPLibre

## Démarrer la base de données

<!-- [common] -->
```bash
sudo systemctl start postgresql.service
```

<!-- [en] -->
## Run ERPLibre

### Method 1

Simply

<!-- [fr] -->
## Exécuter ERPLibre

### Méthode 1

Simplement

<!-- [common] -->
```bash
./run.sh
```

<!-- [en] -->
Without any argument, ERPLibre picks the database for you: with a single
one it starts on it, with several it shows a numbered menu. It only asks
when a real terminal is there — a service started by systemd behaves
exactly as before.

Two options steer that, and neither reaches Odoo:

| option | effect |
|---|---|
| `--auto-erplibre` | pick the database even when other arguments are given |
| `--no-cli-erplibre` | never show the menu; a lone database is still taken |

Naming a database yourself — `-d`, `--database` — turns the whole thing
off, and so does a `db_name` set in the configuration file.

<!-- [fr] -->
Sans aucun argument, ERPLibre choisit la base pour vous : s'il n'y en a
qu'une il démarre dessus, s'il y en a plusieurs il affiche un menu
numéroté. Il ne pose la question que devant un vrai terminal — un service
lancé par systemd se comporte exactement comme avant.

Deux options le pilotent, et aucune n'arrive jusqu'à Odoo :

| option | effet |
|---|---|
| `--auto-erplibre` | choisir la base même quand d'autres arguments sont donnés |
| `--no-cli-erplibre` | ne jamais afficher le menu ; une base seule est quand même retenue |

Nommer soi-même une base — `-d`, `--database` — désactive tout, de même
qu'un `db_name` posé dans le fichier de configuration.

<!-- [en] -->
With arguments

<!-- [fr] -->
Avec des arguments

<!-- [common] -->
```bash
./run.sh -h
```

<!-- [en] -->
### Method 2

Execute your own python script:

<!-- [fr] -->
### Méthode 2

Exécutez votre propre script Python :

<!-- [common] -->
```bash
./run.sh --log-level debug
```

<!-- [en] -->
### Update all

Great idea to run it when updating Odoo, it updates each module database.

<!-- [fr] -->
### Tout mettre à jour

Bonne idée de l'exécuter lors de la mise à jour d'Odoo, cela met à jour la base de données de chaque module.

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -u all --log-level debug
```

<!-- [en] -->
### Update module

<!-- [fr] -->
### Mettre à jour un module

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -u [module] --log-level debug
```

<!-- [en] -->
### Test

First execution, install you requirements, choose a new database.

<!-- [fr] -->
### Test

Première exécution, installez vos dépendances, choisissez une nouvelle base de données.

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -i [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

<!-- [en] -->
Execute your test on a specific module.

<!-- [fr] -->
Exécutez vos tests sur un module spécifique.

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

<!-- [en] -->
Execute your test on a specific module with tags.

<!-- [fr] -->
Exécutez vos tests sur un module spécifique avec des tags.

<!-- [common] -->
```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test --test-tags [module_name][tags]
```

<!-- [en] -->
### Browser tests (tours, hoot)

Odoo tours, hoot tests and every `HttpCase` that drives a browser need two
things, and miss either one silently: each such test raises `SkipTest`, the
run ends green, and only a warning in the log — `Chrome executable not found`
or `websocket-client module is not installed` — tells that nothing ran.

- **A Chrome or Chromium in the `PATH`.** On Linux, Odoo looks for
  `google-chrome`, `chromium`, `chromium-browser` then `google-chrome-stable`;
  on macOS, `Google Chrome.app` then `Chromium.app` under `/Applications`.
  `make install_browser_test` installs one for the detected distribution:
  `chromium` from the system packages on Debian, Linux Mint, Fedora, the RHEL
  family (through EPEL), openSUSE and Arch, Google Chrome on macOS, and the
  Google Chrome `.deb` on Ubuntu, whose `chromium-browser` is a snap: the snap
  has its own `/tmp`, where Odoo never finds the debugging port of the
  browser. A snap Chromium already in the `PATH` therefore does not count as
  installed. On NixOS, declare `chromium` in `environment.systemPackages` or
  run the tests in `nix-shell -p chromium`. The target is not part of
  `make install_os`, a full browser being useless on a production server.
  `--dry-run` shows the commands without running them.
- **The `websocket-client` Python package in the Odoo venv.** It is declared
  in the Odoo 18 dependencies; an existing venv receives it with
  `poetry install --no-root`, run in that venv. When the lock file is older
  than the pyproject, Poetry refuses that command (`pyproject.toml changed
  significantly since poetry.lock was last generated`): run `poetry lock`
  first, in the same venv, with network access.

The script reports both. Then run the tests as above, with a tag that selects
them, for instance `--test-tags=/web:WebSuite` for the hoot suite of `web`.

<!-- [fr] -->
### Tests navigateur (tours, hoot)

Les tours d'Odoo, les tests hoot et tout `HttpCase` qui pilote un navigateur
ont besoin de deux choses, et l'absence de l'une comme de l'autre passe
inaperçue : chacun de ces tests lève `SkipTest`, la passe finit verte, et seul un avertissement au
journal — `Chrome executable not found` ou `websocket-client module is not
installed` — dit que rien n'a tourné.

- **Un Chrome ou un Chromium dans le `PATH`.** Sous Linux, Odoo cherche
  `google-chrome`, `chromium`, `chromium-browser` puis `google-chrome-stable` ;
  sous macOS, `Google Chrome.app` puis `Chromium.app` dans `/Applications`.
  `make install_browser_test` en installe un selon la distribution détectée :
  `chromium` des paquets du système sur Debian, Linux Mint, Fedora, la famille
  RHEL (par EPEL), openSUSE et Arch, Google Chrome sur macOS, et le `.deb` de
  Google Chrome sur Ubuntu, dont le `chromium-browser` est un snap : le snap a
  son propre `/tmp`, où Odoo ne trouve jamais le port de débogage du
  navigateur. Un Chromium snap déjà dans le `PATH` ne compte donc pas comme
  installé. Sur NixOS, déclarer `chromium` dans `environment.systemPackages`
  ou lancer les tests dans `nix-shell -p chromium`. La cible ne fait pas
  partie de `make install_os`, un navigateur complet ne servant à rien sur un
  serveur de production. `--dry-run` affiche les commandes sans les exécuter.
- **Le paquet Python `websocket-client` dans le venv d'Odoo.** Il est déclaré
  dans les dépendances d'Odoo 18 ; un venv existant le reçoit par
  `poetry install --no-root`, lancé dans ce venv. Quand le fichier lock est
  plus ancien que le pyproject, Poetry refuse cette commande (`pyproject.toml
  changed significantly since poetry.lock was last generated`) : lancer
  d'abord `poetry lock`, dans le même venv, avec accès au réseau.

Le script vérifie l'un et l'autre. Lancer ensuite les tests comme plus haut,
avec un tag qui les sélectionne, par exemple `--test-tags=/web:WebSuite` pour
la suite hoot de `web`.

<!-- [common] -->
```bash
make install_browser_test
./script/install/install_browser_test.sh --dry-run
```
