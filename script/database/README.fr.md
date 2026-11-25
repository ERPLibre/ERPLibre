
# Base de données

Cette section concerne le migrateur de base de données du générateur de code.

Cette configuration est pour l'environnement de développement.

Vous devez installer le script `./script/install/install_dev_extra_ubuntu.sh`.

## Restaurer une base de données

Exécutez le script pour restaurer la base de données :

```bash
./script/database/restore_mariadb_sql_example_1.sh
```

## Sauvegarde de production : odoo_backup.py

`odoo_backup.py` prend des sauvegardes vérifiées d'une base Odoo servie par
systemd, au format zip d'Odoo (`dump.sql`, `manifest.json`, `filestore/`),
celui que `/web/database/manager` restaure tel quel. Il en donne aussi
l'âge, les essaie dans une base temporaire et en restaure une dans une
nouvelle base. Il n'a besoin ni du venv Odoo ni de `list_db`. Dans
`make todo` : `TODO › Exécuter › Production › Sauvegardes` (maintenant,
état, restauration d'essai, restauration dans une nouvelle base,
restauration d'essai d'un fichier) et
`TODO › Exécuter › Production › Minuteries systemd` pour la sauvegarde
planifiée.

```bash
./script/database/odoo_backup.py --dry-run
sudo ./script/database/odoo_backup.py --db demo_db
./script/database/odoo_backup.py --status
sudo ./script/database/odoo_backup.py --test-restore --db demo_db
sudo ./script/database/odoo_backup.py --restore --file /var/backups/erplibre/demo_db/demo_db_2031-03-10_03h00m00s.zip --into demo_copy
```

**Détection.** Comme pour `script/odoo/update_module.py` : l'unité
(`--service`, sinon celle dont `WorkingDirectory` est ce checkout, sinon la
seule active), son compte, sa configuration Odoo, la base (`--db`, sinon le
`-d` de l'unité, sinon `db_name`) et son dossier de données, dans l'ordre
d'Odoo : `-D`/`--data-dir` de l'unité, `data_dir` de la configuration (`~`
est le dossier personnel du compte, un chemin relatif part du dossier de
l'unité), `XDG_DATA_HOME` de l'unité, puis `~compte/.local/share/Odoo`.

**Compte.** `pg_dump`, `psql`, `createdb` et `dropdb` tournent sous le
compte de l'unité : directement si c'est le compte courant, par `runuser`
sous root. Tout autre compte est refusé (code 2), sauf avec `--dry-run` et
`--status`. `--dry-run` se passe de sudo : un dossier que seul root peut
créer s'affiche comme le `sudo mkdir` que fera l'exécution réelle. Sous
root, tout fichier d'un dossier qui appartient au compte de l'unité est
créé, donné et lu par son descripteur ouvert, jamais par un chemin que ce
compte pourrait remplacer par un lien symbolique. La connexion est celle
d'Odoo (`db_host`, `db_port`, `db_user`,
`db_password`, `db_sslmode` ; outils cherchés dans `pg_path` s'il est
posé), passée par l'environnement : le mot de passe ne paraît jamais sur
une ligne de commande ni dans la sortie.

**Sauvegarde.** L'espace libre est vérifié avant d'écrire quoi que ce soit :
`(taille de la base + filestore) × 1,2`. `pg_dump --no-owner` s'écrit
directement dans le zip, le filestore est lu après le dump, fichiers
ordinaires seulement (un lien symbolique est écarté et signalé, même posé
pendant la lecture) ; sous root, le dossier du filestore doit appartenir
au compte de l'unité. Le zip
s'écrit en `<nom>.partial`, est relu en entier (CRC de chaque membre,
marque de fin de pg_dump, manifeste lisible), synchronisé, puis renommé en
`<dest>/<base>/<base>_<AAAA-MM-JJ>_<HH>h<MM>m<SS>s.zip`, avec un `.sha256`
à côté (format de `sha256sum -c`). Fichiers en 0600 et dossier de la base
en 0700, au compte de l'unité. Un filestore absent est un avertissement
quand la base ne stocke aucune pièce jointe sur disque, un échec sinon. La
sauvegarde prend le verrou de la base, le même qu'`update_module.py` : une
sauvegarde ne court jamais pendant une mise à jour.

**Rétention**, après une sauvegarde réussie et sur les seuls noms de
l'outil pour cette base : la plus récente de chacun des `--keep-daily`
derniers jours (7), des `--keep-weekly` dernières semaines ISO (4) et des
`--keep-monthly` derniers mois (12) qui en ont une, plus tout ce qui date des
`--keep-recent-days` derniers jours (2), pour qu'une sauvegarde prise avant
une mise à jour survive à la sauvegarde planifiée du même jour. La plus
récente n'est jamais supprimée ; une interruption des sauvegardes n'efface
jamais tout.

**État.** Chaque base a son `<state-dir>/<base>/state.json` (par défaut
`/var/lib/erplibre-backup`) : dernier succès (heure, fichier, taille,
sha256), dernier échec, dernière copie, dernier essai de restauration, les
tâches planifiées actives du module `auto_backup` vues par la dernière
sauvegarde, et le seuil d'âge que l'installeur de la minuterie a déduit du
calendrier. Il est lisible par tous : `--status` se passe de sudo, et ne
lance aucune commande PostgreSQL.

**État des sauvegardes.** `--status` échoue (code 1) quand une base n'a
aucun succès, ou un succès plus vieux que `--max-age` heures ; sans
`--max-age`, le seuil déduit du calendrier tant que la minuterie est
installée, sinon 26. Il échoue aussi quand le dernier essai de restauration
a échoué, ou quand le programme de l'`ExecStart` du service de sauvegarde
n'existe plus (un checkout déplacé fait échouer chaque passage) ; un chemin
que le compte qui lance `--status` ne peut pas examiner (dossier personnel
fermé) n'est qu'un détail. Il signale
un échec plus récent que le dernier succès, un fichier noté absent du
disque, une copie en échec, une minuterie absente ou inactive, un service
sans `--copy-to` (une sauvegarde gardée sur le serveur se perd avec lui),
des tâches actives d'`auto_backup` ou d'`auto_database_backup` qui ont une
configuration de sauvegarde (une seconde sauvegarde depuis Odoo, sur le
même disque ; une tâche sans configuration ne sauvegarde rien), et un essai de restauration absent ou plus vieux que
`--max-restore-age` jours (7). Il donne le nombre et la taille totale des
sauvegardes (leur dossier est au compte de l'unité : sous sudo) et chaque
date avec son décalage UTC, puisque les noms d'archives sont en heure
locale. La minuterie se lit par `systemctl show`, sans root.

**Restauration d'essai.** `--test-restore` restaure la sauvegarde la plus
récente (ou `--file`) dans une base temporaire
`<base>_restoretest_<horodatage>` (raccourcie aux 63 octets de
PostgreSQL), vérifie le sha256, charge `dump.sql`, contrôle les tables,
`ir_module_module`, le module `base` et les modules installés par rapport
au manifeste, extrait le filestore sous le compte de l'unité dans un
dossier provisoire, puis supprime toujours ce qu'elle a créé ; une base
temporaire qu'elle ne peut pas supprimer finit en code 1. La base source
n'est jamais touchée. Les marqueurs du ramasse-miettes d'Odoo 18
(`filestore/checklist/`) ne comptent pas comme pièces jointes quand le
nombre de fichiers que la base référence est comparé à la sauvegarde. Sauf
avec `--dry-run`, l'issue (heure, réussite, fichier, dernière erreur) est
notée dans `last_restore_test`, que `--status` juge, quand le fichier est
une sauvegarde de la base, sous le nom de l'outil, dans son dossier. Le
dossier provisoire
est celui des sauvegardes de la base, ou celui des filestores d'Odoo
quand aucune sauvegarde n'a encore été prise.

**Place dans PostgreSQL.** Une restauration, d'essai ou non, crée une
copie complète sur le même serveur PostgreSQL : un volume plein arrêterait
aussi la base de production. Avant `createdb`, l'outil vérifie l'espace
libre du `data_directory` de PostgreSQL pour le double de `dump.sql` (les
index sont reconstruits), ou la taille de la base source si elle est plus
grande, plus 20 %. Le dossier se lit sous le rôle de l'unité, sinon, sous
root, sous le compte système `postgres` par la socket locale. Illisible,
ou `db_host` sur un autre hôte, l'outil refuse, sauf `--force-space`.

**Restauration.** `--restore --file F --into NOUVELLE` ne restaure que dans
une base qui n'existe pas encore, et un dossier
`<data_dir>/filestore/NOUVELLE` qui n'existe pas non plus. Les chemins
d'archive qui sortiraient du dossier d'extraction sont refusés. `--file`
prend aussi un `.tar.xz` de l'ancien outil de sauvegarde (`dump.sql`,
`manifest.json` et `filestore/` à sa racine, le contenu du zip), reconnu à
ses premiers octets : un lien, un fichier spécial ou un nom en double y
refuse l'archive. L'outil n'en écrit jamais. Le filestore s'écrit sous le
compte de l'unité. Un échec après `createdb`
supprime la nouvelle base et son filestore provisoire.
Avant d'y démarrer Odoo, la neutraliser (`odoo-bin neutralize`, dès Odoo
16) ; son `database.uuid` est celui de la source.

**Dans un checkout de développement.** Le zip a le format d'Odoo, donc
`db_restore.py` le restaure sur un poste de développement : une `--image`
qui contient un `/` est un chemin, lu tel quel et restauré sans copie
`_cache_`. Une base qui porte déjà le nom de `-d` est d'abord supprimée.

```bash
./script/database/db_restore.py -d demo_copy --neutralize --image ~/Downloads/demo_db_2031-03-10_03h00m00s.zip
./script/addons/update_prod_to_dev.sh demo_copy
```

`--neutralize` fait neutraliser la base par Odoo pendant son chargement
(dès Odoo 16 : crons et serveurs de courriel coupés) ; `update_prod_to_dev.sh`
installe ensuite les modules de développement (compte `test`/`test`,
courriel sortant, sauvegardes automatiques et fournisseurs de paiement
désactivés). `TODO › Exécuter › Database › Restaurer a partir d'une sauvegarde
(.zip)` pose les mêmes questions pour un zip rangé dans
`image_db/`.

**Copie hors site.** `--copy-to [compte@]hôte:/chemin` (ou un chemin
absolu), désactivée par défaut, suit la rétention : rsync sur
`ssh -o BatchMode=yes`, sous le compte de l'unité, donc avec sa clé ssh et
son `known_hosts`. Elle envoie le dossier de la base, filtré sur les noms
de l'outil pour cette base (`<base>_<horodatage>.zip` et son `.sha256`) :
une copie manquée ou tronquée à un passage repart au suivant. Un
transfert interrompu attend dans `.rsync-partial/` et ne prend jamais le nom
final (`--partial-dir`, `--delay-updates`). Une copie en échec garde la
sauvegarde locale, est notée et finit en code 1. `--copy-prune` liste
ensuite la destination (`rsync --list-only`) et applique la même rétention
aux sauvegardes qui s'y trouvent : celles qu'elle ne garde pas sont
supprimées, chacune avec son `.sha256`, jamais une encore présente en
local, au plus `--copy-prune-max` sauvegardes par passage (20), les plus
anciennes d'abord. L'historique distant est jugé pour lui-même : un serveur
reconstruit, une nouvelle destination ou des sauvegardes locales
supprimées à la main ne font jamais supprimer plus que ce que la rétention
garde. Aucun autre fichier distant n'est supprimé (seuls les noms visés
sont inclus), et un dossier local vide ou illisible n'envoie rien. Un
élagage en échec ou arrêté sur la limite est un avertissement : les
sauvegardes sont copiées. Sans `--copy-prune`, le côté distant grossit.

**Sauvegardes de l'ancien outil.** Ses archives s'appellent
`<base>_<AAAA-MM-JJ>_<HHMMSS>.zip` ou `.tar.xz` : la rétention, `--status`
et le choix de la sauvegarde la plus récente les ignorent, et
`--copy-prune` ne les supprime jamais à distance. En restaurer ou en
essayer une par `--file` (l'essai d'un fichier qui n'est pas une sauvegarde
de la base dans son dossier n'est pas noté pour `--status`), puis les supprimer à la main une fois la période
couverte par les nouvelles sauvegardes :

```bash
sudo ./script/database/odoo_backup.py --test-restore --db demo_db --file /var/backups/odoo/demo_db/demo_db_2031-03-09_030000.tar.xz
```

**Profil.** Les réglages durables d'une instance vivent dans son profil
JSON, groupe `backup` : `dest`, `state_dir` (chemins absolus), `keep_daily`
(au moins 1), `keep_weekly`, `keep_monthly`, `keep_recent_days` (au moins 2
à eux tous, le défaut de l'outil comptant pour une valeur que la ligne de
commande remplace), `copy_to`, `copy_prune`, `copy_prune_max` (au moins
1), `max_age` (au plus 168), `max_restore_age`, `timeout`, `verbose`, et
`db` du groupe partagé `instance`. Le fichier est `--profile FICHIER`,
sinon `private/production/<service>.json` de ce checkout, le service étant
`--service` ou l'unité devinée ; pas de fichier, pas de profil. La ligne de
commande gagne toujours ; `--no-profile` ne lit aucun profil,
`--profile-unset NOM` (ex. `keep-daily`) en retire une valeur,
`--profile-required` échoue (code 2) sans profil. Les modes, `--file`,
`--into`, `--service`, `--odoo-conf`, `--user`, `--force-space` et
`--dry-run` ne se lisent jamais d'un profil : une telle clé est ignorée
avec un avertissement. `--status` ne devine aucune unité et écarte la `db`
du profil : il liste toujours chaque base. Les valeurs du profil
s'affichent sous l'instance détectée, avant les commandes simulées.

```json
{
  "version": 1,
  "service": "odoo-exemple.service",
  "instance": {"db": "exemple_db"},
  "backup": {"dest": "/srv/sauvegardes", "keep_daily": 10,
             "copy_to": "sauvegarde@backup.example.org:/srv/hors-site"}
}
```

**Limites d'envoi.** Une sauvegarde envoyée par `/web/database/manager`
passe par la limite de taille de requête du mandataire inverse
(`client_max_body_size` pour nginx) et par la limite de durée de requête
d'Odoo (`limit_time_real`, avec des workers) : pour une grosse base, la
restaurer sur le serveur avec `--restore`.

| Code | Sens |
|------|------|
| 0 | réussi (ou simulation) |
| 1 | échec : sauvegarde, vérification, copie, état trop ancien ou absent, restauration d'essai, base temporaire non supprimée |
| 2 | refusé avant de rien faire |
| 75 | une autre sauvegarde ou mise à jour de cette base est en cours |
| 130 | interrompu ; le fichier provisoire est retiré |

La sauvegarde planifiée s'installe par
`script/systemd/install_backup_timer.py`, voir
[doc/PRODUCTION.fr.md](../../doc/PRODUCTION.fr.md). Il lit le même
profil : son propre groupe `backup_timer` (`on_calendar`,
`randomized_delay`, `verbose`), plus `dest`, `state_dir`, les réglages
`keep_*`, `copy_to`, `copy_prune` et `copy_prune_max` de `backup` (les deux
derniers écrits avec `--copy-to` seulement), et `db` d'`instance`. Il
déduit le seuil d'âge de `--status` du calendrier : le plus grand écart
entre deux des 64 prochaines échéances (`systemd-analyze calendar
--iterations`), plus le délai aléatoire et 2 h, noté sous
`expected_max_age_hours` dans l'état de la base ; quand aucun seuil ne se
déduit (systemd trop ancien pour `--iterations`, sortie illisible), il
garde 26 h, avec un avertissement, et efface le seuil d'une installation
précédente. Il finit en
rappelant de lancer un essai de restauration. `--on-calendar`
et `--randomized-delay` refusent une valeur mal formée dès l'analyse
(code 2), qu'elle vienne de la ligne de commande ou du profil ;
`systemd-analyze calendar` vérifie encore le calendrier à l'installation.
La ligne de commande gagne toujours, et les mêmes méta-options
s'appliquent (`--profile`, `--no-profile`, `--profile-unset`,
`--profile-required`). `--uninstall`, `--service`, `--odoo-conf`,
`--user`, `--root`, `--credential` et `--dry-run` ne se lisent jamais
d'un profil. Les valeurs retenues s'affichent avant les unités et les
commandes simulées.

`ExecStart` prend l'une de deux formes :

- **mode profil**, quand un profil est retenu, que le compte de l'unité
  peut le lire (`runuser -u COMPTE -- test -r`, vérifié sous sudo) et que
  l'outil du checkout retenu l'applique (lecture statique, rien n'est
  exécuté) : l'identité détectée (`--service`, `--db`, `--odoo-conf`,
  `--user`), les champs fixés à l'installation (`--dest`, `--state-dir`,
  `--copy-to`) quelle que soit leur origine, les réglages `--keep-*`
  seulement s'ils sont tapés, puis `--profile <chemin absolu>
  --profile-required`. La sauvegarde relit le profil à chaque passage :
  une rétention éditée vaut dès la nuit suivante, et un profil devenu
  invalide fait échouer la sauvegarde (code 2, vu par `--status`) plutôt
  que de perdre `--copy-to` en silence. `systemctl cat` montre le chemin.
  Sous root, l'outil ne lit qu'un profil que ni son groupe ni les autres
  comptes ne peuvent écrire, ni son dossier, et qui appartient à root, au
  propriétaire du checkout ou à l'appelant de sudo.
- **mode figé** sinon (pas de profil, profil illisible par le compte,
  outil antérieur au profil) : toutes les valeurs écrites comme si elles
  avaient été tapées, comme avant, terminées par `--no-profile` quand
  l'outil connaît le profil. Avec un profil présent, un avertissement dit
  qu'une édition du profil demande une réinstallation.

`--dest`, `--state-dir`, `--copy-to`, `--db`, `--on-calendar` et
`--randomized-delay` sont fixés à l'installation (fichier de la minuterie,
dossiers créés au compte, son `known_hosts`) : après les avoir changés
dans le profil, réinstaller.

**Secrets.** `--credential NOM=CHEMIN` (répétable) transmet un secret que
l'outil de sauvegarde déclare ; `backup` n'en déclare aucun aujourd'hui,
le chemin est générique. Root lit `CHEMIN` sans suivre de lien et le
range en credential systemd de l'unité, jamais sur une ligne de commande
ni dans l'environnement :

| systemd | Stockage | Ligne d'unité |
|---|---|---|
| 250 et plus avec `systemd-creds` | `systemd-creds encrypt --with-key=host`, secret sur l'entrée standard, `/etc/credstore.encrypted/<unité>.<NOM>` (0600, dossier 0700) | `LoadCredentialEncrypted=` |
| 247 à 249, ou sans `systemd-creds` | en clair, `/etc/credstore/<unité>.<NOM>` (0600 root, dossier 0700), avec un avertissement | `LoadCredential=` |
| avant 247, ou inconnue | refus (code 2) avant toute écriture | — |

Seul un `systemd-creds` absent (code 127) mène au stockage en clair : tout
autre échec de `systemd-creds --version` sous systemd 250 et plus est
refusé (code 2) plutôt que rangé en clair. Les lignes d'unité portent des
chemins absolus. Un fichier chiffré avec `--with-key=host` ne se lit
qu'avec `/var/lib/systemd/credential.secret` de l'hôte : restaurer `/etc`
seul rend l'unité incapable de démarrer. Un secret que le profil déclare
sans `--credential` garde le fichier rangé, d'abord celui que cite
l'unité en place, avec sa ligne, même après une mise à jour de systemd
(un fichier gardé en clair alors que le chiffrement est possible donne un
avertissement), et refuse s'il n'y en a pas ; `--dry-run` ne lit rien et
montre la ligne « (fourni à l'installation) ». Une réinstallation retire
la ligne et le fichier d'un secret que le profil ne déclare plus ; un
fichier rangé par une installation qui échoue avant d'écrire le service
est retiré aussitôt. `--uninstall` retire les fichiers de credential de
l'unité, seulement sous `/etc/credstore` ou `/etc/credstore.encrypted` et
nommés d'après l'unité : ceux que cite l'unité, `<unité>.<NOM>` pour
chaque secret de l'outil, et les restes temporaires d'une écriture
interrompue (`--root` les préfixe ; `--dry-run` montre les `rm`, marqués
« (s'il existe) » quand, sans root, le dossier 0700 ne se vérifie pas).