
# Installation de Selenium

Les scripts tournent dans le venv d'outillage, `.venv.erplibre`, qui contient
déjà `selenium` et `pykeepass`. `requirements.txt` ajoute le reste, dont
aucun ne demande de bibliothèque système ; `requirements-video.txt` ajoute
l'enregistreur vidéo, PyGObject, compilé contre les bibliothèques système
ci-dessous.
`script/install/install_debian_dependency.sh` les installe sur Debian et
Ubuntu.

```bash
.venv.erplibre/bin/pip install -r script/selenium/requirements.txt

sudo apt install libcairo2-dev python3-dev pkg-config libxt-dev libgirepository-2.0-dev ffmpeg
.venv.erplibre/bin/pip install -r script/selenium/requirements-video.txt
```

PyGObject, qui tire pycairo, se compile dès la 3.50 contre girepository-2.0
et exige GLib 2.80 : Debian 13 et Ubuntu 24.04 l'ont, Debian 12 non, et
l'enregistrement vidéo n'y est pas disponible. `ffmpeg` convertit les
enregistrements en MP4.

geckodriver ne demande aucune installation : Selenium Manager, livré avec
`selenium`, le télécharge dans `~/.cache/selenium` au premier usage. Le
Firefox piloté est le snap d'Ubuntu, sinon `firefox`, sinon `firefox-esr`,
son nom sous Debian.

Enregistreur vidéo : https://github.com/szemate/pyselenium-video-recorder

## Avec le compose Docker

L'image ERPLibre n'a ni navigateur ni affichage.
`docker/docker-compose_odoo_18.0_selenium.yml` démarre Odoo à côté d'une
grille Selenium, et les scripts tournent depuis le checkout de l'hôte, dans
son `.venv.erplibre`, jamais dans le conteneur ERPLibre : le compte qui fait
tourner Odoo ne doit lire ni le coffre KeePass ni son mot de passe, et le
compose n'y monte donc pas `private/`.

Les scripts pilotent la grille par son routeur, publié sur `127.0.0.1:8075`.
Le navigateur tourne dans un nœud, sans affichage puisque les nœuds n'en ont
pas : passez `--headless`, sans quoi la session ne démarre pas. Il atteint
Odoo par son nom de service : donnez `--url http://ERPLibre:8069`, car la
valeur par défaut, `http://127.0.0.1:8069`, désigne le nœud lui-même, où
aucun Odoo ne répond. Certains scripts appellent aussi Odoo depuis l'hôte
avec la même URL, dont `run_requirement_tours.py`, qui liste les bases par
XML-RPC ; Odoo est publié sur `127.0.0.1:8069` de l'hôte, si bien qu'une
ligne dans le `/etc/hosts` de l'hôte fait fonctionner `http://ERPLibre:8069`
des deux côtés. Les nœuds renvoient les téléchargements au script sur l'hôte
(téléchargements gérés, actifs par défaut dans leurs images).

```bash
grep -qw ERPLibre /etc/hosts || echo "127.0.0.1 ERPLibre" | sudo tee -a /etc/hosts
```

Trois réseaux tiennent la grille hors de portée d'Odoo. Le hub et les nœuds
partagent `grid`, où ERPLibre n'est pas : ni le routeur, ni le bus
d'événements, ni le serveur Selenium d'un nœud ne lui répondent. Les nœuds
rejoignent ERPLibre sur `web` pour charger ses pages, et leur serveur
Selenium n'y écoute pas. PostgreSQL est sur `backend`, avec ERPLibre seul.
Les nœuds ne lancent ni affichage X, dont le serveur accepterait tout client
de `web`, ni serveur VNC, dont le mot de passe est une valeur par défaut
publique dans l'image.

Le routeur demande un utilisateur et un mot de passe (authentification
Basic) à chaque requête, `/status` compris, qui liste les sessions : avec la
séparation des réseaux, ils gardent les sessions et ce que tapent les
scripts. Le secret d'enregistrement garde autre chose : le hub n'accepte un
nœud que s'il porte le même secret, si bien qu'aucun autre conteneur ne peut
en enregistrer un et recevoir les sessions.

Aucun ne passe par une variable d'environnement. Les scripts de démarrage de
l'image font de `SE_ROUTER_USERNAME`, `SE_ROUTER_PASSWORD` et
`SE_REGISTRATION_SECRET` des arguments de la commande `java`, que tout compte
de l'hôte lit avec `ps` : avec Docker sans root, les processus d'un conteneur
sont des processus de l'hôte. Le compose ne pose aucune des trois ; Selenium
les lit dans deux fichiers TOML que le compose monte en lecture seule et lui
passe par `--config` :

- `selenium-hub.toml`, pour le hub : `[router]` `username` et `password`,
  `[server]` `registration-secret` ;
- `selenium-node.toml`, pour chaque nœud : `[server]` `registration-secret`
  seul. Selenium le fusionne avec la configuration que l'image génère à
  chaque démarrage à partir des variables `SE_NODE_*`.

`selenium.env`, le fichier à passer par `--env-file` à chaque commande du
compose, nomme les deux fichiers et ne porte aucun secret : sans lui, `up`,
`create` et `config` s'arrêtent avant de toucher à quoi que ce soit, et un
chemin où aucun fichier n'existe arrête la création du conteneur. Après une
nouvelle génération des secrets, `up` recrée le hub et les nœuds pour qu'ils
lisent les nouveaux fichiers. Un `.env` à la racine du checkout serait lu sans l'option, mais
git ne l'ignore pas. `selenium-router.env` porte les identifiants du routeur
pour les scripts, et rien d'autre.

Les quatre fichiers vivent hors du checkout, dans `~/.config/erplibre`, en
mode 700. Dans le conteneur, Selenium tourne sous `seluser`, uid 1200, groupe
1201 : les deux fichiers TOML vous gardent pour propriétaire et prennent le
groupe 1201 du conteneur, en mode 640. Un conteneur jetable de l'image du hub
pose ce groupe, car les identifiants doivent être ceux du conteneur : avec
Docker sans root, le groupe 1201 correspond à un sous-gid de `/etc/subgid`,
que ne porte aucun compte de l'hôte, si bien que seuls vous et la grille les
lisez. Avec un démon Docker lancé par root, la même commande donne les
fichiers à root et au groupe 1201 de l'hôte : `getent group 1201` ne doit
d'abord rien répondre, et une réécriture ultérieure passe par `sudo`.

```bash
mkdir -p ~/.config/erplibre && chmod 700 ~/.config/erplibre
(umask 077 && cd ~/.config/erplibre && python3 - <<'EOF'
import os, secrets
secret, password = secrets.token_hex(32), secrets.token_hex(32)
files = {
    "selenium-hub.toml": f'[router]\nusername = "erplibre"\n'
    f'password = "{password}"\n\n[server]\nregistration-secret = "{secret}"\n',
    "selenium-node.toml": f'[server]\nregistration-secret = "{secret}"\n',
    "selenium-router.env": "SELENIUM_ROUTER_USERNAME=erplibre\n"
    f"SELENIUM_ROUTER_PASSWORD={password}\n",
    "selenium.env": f"SELENIUM_HUB_CONFIG={os.getcwd()}/selenium-hub.toml\n"
    f"SELENIUM_NODE_CONFIG={os.getcwd()}/selenium-node.toml\n",
}
for name, text in files.items():
    with open(name, "w") as f:
        f.write(text)
EOF
)
docker run --rm --network none -u 0 --entrypoint sh \
  -v ~/.config/erplibre/selenium-hub.toml:/s/hub.toml \
  -v ~/.config/erplibre/selenium-node.toml:/s/node.toml \
  selenium/hub:4.34.0-20250707 \
  -c 'chown 0:1201 /s/hub.toml /s/node.toml && chmod 640 /s/hub.toml /s/node.toml'
```

Les scripts lisent les identifiants du routeur dans
`SELENIUM_ROUTER_USERNAME` et `SELENIUM_ROUTER_PASSWORD` ; le sous-shell
ci-dessous exporte `selenium-router.env`, qui porte ces deux-là et rien
d'autre, pour le seul script.
`--use_network http://USER:PASSWORD@127.0.0.1:8075` fonctionne aussi, mais
met le mot de passe dans la liste des processus et l'historique du shell.

La grille fait confiance aux pages que chargent ses navigateurs. Une page
servie par un Odoo compromis tourne dans le navigateur du nœud, à côté du
serveur Selenium du nœud lui-même : par le navigateur, en rebinding DNS par
exemple, elle peut atteindre ce serveur et lire ce que rendent les points
d'accès GET de la session. Ne mêlez pas, dans une même session, des
identifiants de tiers, dont ceux du coffre KeePass, à un Odoo auquel vous ne
faites pas confiance.

`.venv.erplibre` n'épingle pas `selenium` : un client 4.x pilote la grille
4.34 du compose, et une commande que la grille ne connaît pas encore échoue
seule. Montez la version de la grille quand un script demande une commande
plus récente.

```bash
docker compose --project-directory . --env-file "$HOME/.config/erplibre/selenium.env" \
  -f docker/docker-compose_odoo_18.0_selenium.yml up -d
(set -a && . ~/.config/erplibre/selenium-router.env && set +a &&
  exec .venv.erplibre/bin/python script/selenium/SCRIPT.py --headless \
    --use_network http://127.0.0.1:8075 --url http://ERPLibre:8069)
```

Un script qui se connecte avec le coffre KeePass le trouve à `kdbx.path` dans
`private/todo/todo_override_private.json`. `KDBX_PASSWORD_FILE` nomme un
fichier qui porte le mot de passe ; la valeur elle-même reste hors de
l'environnement et du JSON. Une fois posée, la variable l'emporte sur
`kdbx.password` et sur l'invite, terminal ou non, ce qui permet à un script de
tourner sans surveillance ; un fichier illisible, comme un coffre qui ne s'ouvre
pas, arrête le script avec sa cause.

Le fichier se trouve hors du checkout, `~/.config/erplibre/kdbx_password` par
exemple, vous appartient, en mode 600. Jamais dans `private/` : ce répertoire
peut être commité ou sauvegardé à côté du coffre, et le mot de passe voyagerait
alors avec le coffre qu'il ouvre. Le chemin se lit tel qu'écrit, sans
développement de `~` : donnez-le par `$HOME`.

```bash
mkdir -p ~/.config/erplibre && chmod 700 ~/.config/erplibre
(umask 077 && IFS= read -rs -p "Vault password: " pw && echo &&
  printf '%s\n' "$pw" >~/.config/erplibre/kdbx_password)
chmod 600 ~/.config/erplibre/kdbx_password
export KDBX_PASSWORD_FILE="$HOME/.config/erplibre/kdbx_password"
```