
# Exécuter ERPLibre

## Démarrer la base de données

```bash
sudo systemctl start postgresql.service
```

## Exécuter ERPLibre

### Méthode 1

Simplement

```bash
./run.sh
```

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

Avec des arguments

```bash
./run.sh -h
```

### Méthode 2

Exécutez votre propre script Python :

```bash
./run.sh --log-level debug
```

### Tout mettre à jour

Bonne idée de l'exécuter lors de la mise à jour d'Odoo, cela met à jour la base de données de chaque module.

```bash
./run.sh -d [DATABASE] -u all --log-level debug
```

### Mettre à jour un module

```bash
./run.sh -d [DATABASE] -u [module] --log-level debug
```

### Test

Première exécution, installez vos dépendances, choisissez une nouvelle base de données.

```bash
./run.sh -d [DATABASE] -i [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

Exécutez vos tests sur un module spécifique.

```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

Exécutez vos tests sur un module spécifique avec des tags.

```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test --test-tags [module_name][tags]
```

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

```bash
make install_browser_test
./script/install/install_browser_test.sh --dry-run
```