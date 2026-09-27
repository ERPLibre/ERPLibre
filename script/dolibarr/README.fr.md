
# Dolibarr

ERPLibre installe et fait tourner [Dolibarr](https://www.dolibarr.org/),
l'ERP en PHP, à côté d'Odoo. La version de Dolibarr est épinglée : un commit
du dépôt officiel, que Google Repo récupère dans `dolibarr/dolibarr`.

Depuis TODO :

- `Installation › Dolibarr` installe une instance ;
- `Exécution › Dolibarr` lance, arrête et suit les instances de
  développement, et relève le commit épinglé.

Chaque entrée de TODO lance un script de ce dossier avec ses paramètres ;
chaque script se lance aussi seul.

## Scripts

| Script | Rôle |
|--------|------|
| `install_native.py` | Installe une instance avec nginx, PHP-FPM et MariaDB ou PostgreSQL |
| `native_prod.py` | Étapes de production, jouées par `install_native.py --mode prod` |
| `run.py` | `start`, `stop`, `status`, `logs` d'une instance de développement |
| `pin.py` | `show` le commit épinglé, `update` le relève (à blanc sans `--apply`) |
| `lib_dolibarr.py` | Décisions pures : épinglage, noms, ce que l'hôte permet |
| `packages.py` | Noms de paquets et chemins par famille de distribution |
| `web_config.py`, `units.py`, `install_files.py` | Rendu pur des fichiers nginx, PHP-FPM, systemd et d'installation |

Familles prises en charge : Debian/Ubuntu (apt), Fedora/EL (dnf), Arch
(pacman), openSUSE (zypper).

## Développement

```bash
./script/dolibarr/install_native.py --mode dev --db mariadb --instance erp --port 8080
./script/dolibarr/run.py start --instance erp
./script/dolibarr/run.py status
./script/dolibarr/run.py logs --instance erp --lines 40
./script/dolibarr/run.py stop --instance erp
```

nginx et PHP-FPM tournent sous votre compte sur `127.0.0.1:<port>` ; rien ne
va dans `/etc`. Le code est le checkout lui-même : une modification dans
`dolibarr/dolibarr/htdocs` se voit au chargement suivant. Le reste de
l'instance vit dans `~/.local/share/ERPLibre/dolibarr/<instance>` :
documents, `run/` (pid, socket, journaux) et `secrets.env` (0600 : mots de
passe de la base et de l'administrateur).

Le mot de passe administrateur est demandé par TODO, ou généré s'il reste
vide. En ligne de commande, il vient de la variable d'environnement
`EL_DOLIBARR_ADMIN_PASSWORD`, jamais d'un argument.

## Production

```bash
./script/dolibarr/install_native.py --mode prod --db mariadb --instance erp \
    --domain erp.example.org --tls certbot --email ops@example.org
```

La production exige systemd et un nom de domaine. Disposition d'une
instance `<i>` :

- code : `/opt/erplibre-dolibarr/<i>`, exporté du commit épinglé, à root et
  en lecture seule ;
- données : `/var/lib/erplibre-dolibarr/<i>` (documents, sessions), au
  compte système `dolibarr_<i>` ;
- secrets, clé cron, copie de `conf.php`, certificat local :
  `/etc/erplibre-dolibarr/<i>`, root, 0700 ;
- PHP-FPM : un pool sous `dolibarr_<i>`, dont seul nginx lit la socket ;
- nginx : un site là où la distribution les range ;
- tâches planifiées : `erplibre-dolibarr-cron-<i>.timer` lance les tâches
  de Dolibarr toutes les 5 minutes.

`conf.php` finit en lecture seule pour le compte de l'instance, `prod`
allumé. `--tls` choisit le certificat : `certbot` (Let's Encrypt, nom
public ; certbot est installé, depuis EPEL sur EL), `local` (pour les
essais : signé par l'autorité locale du mandataire inverse,
`~/.erplibre/reverse_proxy_tls/ca.crt`, importée une fois dans le
navigateur) ou `none` (HTTP seul). Chaque site nginx ferme la connexion sur
tout autre nom que le sien.

Chaque secret est écrit dans `secrets.env` avant que la base soit touchée :
une installation arrêtée par une erreur reprend, relancée, avec les mêmes
mots de passe.

Limite connue : SELinux en mode enforcing est refusé tant que ses contextes
ne sont pas posés.

## Version épinglée

```bash
./script/dolibarr/pin.py show
./script/dolibarr/pin.py update                 # dry run: what would change
./script/dolibarr/pin.py update --apply
./script/manifest/update_manifest_local_dolibarr.sh
```

`conf/supported_version_dolibarr.json` et `manifest/git_manifest_dolibarr.xml`
bougent ensemble. L'étiquette de l'image Docker ne suit que si Docker Hub la
publie.

Le checkout appartient à Google Repo : un projet sorti du manifest fusionné
est effacé au sync suivant, `conf.php` compris. ERPLibre fusionne le
manifest Dolibarr d'office dès que `dolibarr/dolibarr` existe, et garde une
copie de `conf.php` dans le dossier d'état de l'instance.