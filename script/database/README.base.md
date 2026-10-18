<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Database

This section is for code generator database migrator.

This configuration is for development environnement.

You need to install script `./script/install/install_dev_extra_ubuntu.sh`.

## Restore database

Run script to restore database:

<!-- [fr] -->
# Base de données

Cette section concerne le migrateur de base de données du générateur de code.

Cette configuration est pour l'environnement de développement.

Vous devez installer le script `./script/install/install_dev_extra_ubuntu.sh`.

## Restaurer une base de données

Exécutez le script pour restaurer la base de données :

<!-- [common] -->
```bash
./script/database/restore_mariadb_sql_example_1.sh
```

<!-- [en] -->
## Production backup: odoo_backup.py

`odoo_backup.py` takes verified backups of an Odoo database run by systemd,
in Odoo's own zip format (`dump.sql`, `manifest.json`, `filestore/`), the
one `/web/database/manager` restores as is. It also reports their age,
test-restores them into a temporary database, and restores one into a new
database. It needs neither the Odoo venv nor `list_db`.

<!-- [fr] -->
## Sauvegarde de production : odoo_backup.py

`odoo_backup.py` prend des sauvegardes vérifiées d'une base Odoo servie par
systemd, au format zip d'Odoo (`dump.sql`, `manifest.json`, `filestore/`),
celui que `/web/database/manager` restaure tel quel. Il en donne aussi
l'âge, les essaie dans une base temporaire et en restaure une dans une
nouvelle base. Il n'a besoin ni du venv Odoo ni de `list_db`.

<!-- [common] -->
```bash
./script/database/odoo_backup.py --dry-run
sudo ./script/database/odoo_backup.py --db demo_db
./script/database/odoo_backup.py --status
sudo ./script/database/odoo_backup.py --test-restore --db demo_db
sudo ./script/database/odoo_backup.py --restore --file /var/backups/erplibre/demo_db/demo_db_2031-03-10_03h00m00s.zip --into demo_copy
```

<!-- [en] -->
**Detection.** As for `script/odoo/update_module.py`: the unit
(`--service`, else the one whose `WorkingDirectory` is this checkout, else
the only active one), its account, its Odoo configuration, the database
(`--db`, else `-d` of the unit, else `db_name`) and its data directory, in
Odoo's order: `-D`/`--data-dir` of the unit, `data_dir` of the
configuration (`~` is the account's home, a relative path starts from the
unit's directory), `XDG_DATA_HOME` of the unit, then
`~account/.local/share/Odoo`.

**Account.** `pg_dump`, `psql`, `createdb` and `dropdb` run as the unit's
account: directly when it is the current account, through `runuser` as
root. Any other account is refused (code 2), except with `--dry-run` and
`--status`. `--dry-run` needs no sudo: a folder that only root can create
is shown as the `sudo mkdir` the real run will do. As root, every file in
a folder the unit's account owns is created, given away and read through
its open descriptor, never by a path the account could swap for a
symbolic link. The connection is Odoo's (`db_host`, `db_port`, `db_user`,
`db_password`, `db_sslmode`; tools found in `pg_path` when set), passed
through the environment: the password never appears on a command line nor
in the output.

**Backup.** The free space is checked before anything is written:
`(database size + filestore) × 1.2`. `pg_dump --no-owner` is streamed
straight into the zip, the filestore is read after the dump, regular files
only (a symbolic link is skipped and reported, even one swapped in during
the read); as root, the filestore folder must belong to the unit's
account. The zip is written as
`<name>.partial`, read back in full (CRC of every member, pg_dump end
marker, readable manifest), synced, then renamed to
`<dest>/<db>/<db>_<YYYY-MM-DD>_<HH>h<MM>m<SS>s.zip`, with a `.sha256`
next to it (`sha256sum -c` format). Files are 0600 and the database folder
0700, owned by the unit's account. A missing filestore is a warning when
the database stores no attachment on disk, a failure otherwise. The
backup takes the database lock, the same as `update_module.py`: a backup
never runs during an update.

**Retention**, after a successful backup and only on the tool's own file
names for this database: the newest backup of each of the last
`--keep-daily` days (7), `--keep-weekly` ISO weeks (4) and
`--keep-monthly` months (12) that have one, plus everything from the last
`--keep-recent-days` days (2), so that a backup taken before an update
survives the scheduled one of the same day. The newest backup is never
deleted; a gap in backups never deletes everything.

**State.** Each database has `<state-dir>/<db>/state.json` (default
`/var/lib/erplibre-backup`): last success (time, file, size, sha256), last
failure, last copy. It is readable by everyone, so `--status` needs no
sudo. `--status` fails (code 1) when a database has no success, or one
older than `--max-age` hours (26); it warns about a failure newer than the
last success, a recorded file missing on disk, and a failed copy.

**Test restore.** `--test-restore` restores the newest backup (or
`--file`) into a temporary database `<db>_restoretest_<stamp>` (cut to
fit PostgreSQL's 63 bytes), checks the sha256, loads `dump.sql`, checks the
tables, `ir_module_module`, the `base` module and the installed modules
against the manifest, extracts the filestore as the unit's account into a
temporary folder, then always drops what it created; a temporary database
it cannot drop ends with code 1. The source database is never touched.

**Room in PostgreSQL.** A test restore or a restore creates a full copy on
the same PostgreSQL server: a full volume would stop the production
database too. Before `createdb`, the tool checks the free space of
PostgreSQL's `data_directory` for twice the size of `dump.sql` (indexes
are rebuilt), or the size of the source database when it is larger, plus
20 %. The folder is read as the unit's role, else, as root, as the
`postgres` system account over the local socket. When it cannot be read,
or `db_host` is another host, the tool refuses, unless `--force-space`.

**Restore.** `--restore --file F --into NEW` only restores into a database
that does not exist yet, and a filestore folder
`<data_dir>/filestore/NEW` that does not exist either. Archive paths that
would leave the extraction folder are refused. The filestore is written as
the unit's account. A failure after `createdb` drops the new database and
its partial filestore. Before starting Odoo on
the copy, neutralize it (`odoo-bin neutralize`, from Odoo 16); its
`database.uuid` is the source's.

**Off-site copy.** `--copy-to [user@]host:/path` (or an absolute path),
disabled by default: `rsync -a --partial` over `ssh -o BatchMode=yes`, as
the unit's account, so its ssh key and `known_hosts` are used. A failed
copy keeps the local backup, is recorded, and ends with code 1. Retention
does not apply on the remote side: it keeps growing.

**Upload limits.** A backup uploaded through `/web/database/manager` goes
through the reverse proxy's request size limit (`client_max_body_size` for
nginx) and Odoo's request time limit (`limit_time_real`, with workers): for
a large database, restore it on the server with `--restore`.

| Code | Meaning |
|------|---------|
| 0 | success (or simulation) |
| 1 | failure: backup, verification, copy, stale or missing status, test restore, temporary database not dropped |
| 2 | refused before anything was done |
| 75 | another backup or update of this database is running |
| 130 | interrupted; the partial file is removed |

The scheduled backup is installed by `script/systemd/install_backup_timer.py`,
see [doc/PRODUCTION.md](../../doc/PRODUCTION.md).

<!-- [fr] -->
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
sha256), dernier échec, dernière copie. Il est lisible par tous : `--status`
se passe de sudo. `--status` échoue (code 1) quand une base n'a aucun
succès, ou un succès plus vieux que `--max-age` heures (26) ; il signale un
échec plus récent que le dernier succès, un fichier noté absent du disque
et une copie en échec.

**Restauration d'essai.** `--test-restore` restaure la sauvegarde la plus
récente (ou `--file`) dans une base temporaire
`<base>_restoretest_<horodatage>` (raccourcie aux 63 octets de
PostgreSQL), vérifie le sha256, charge `dump.sql`, contrôle les tables,
`ir_module_module`, le module `base` et les modules installés par rapport
au manifeste, extrait le filestore sous le compte de l'unité dans un
dossier provisoire, puis supprime toujours ce qu'elle a créé ; une base
temporaire qu'elle ne peut pas supprimer finit en code 1. La base source
n'est jamais touchée.

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
d'archive qui sortiraient du dossier d'extraction sont refusés. Le
filestore s'écrit sous le compte de l'unité. Un échec après `createdb`
supprime la nouvelle base et son filestore provisoire.
Avant d'y démarrer Odoo, la neutraliser (`odoo-bin neutralize`, dès Odoo
16) ; son `database.uuid` est celui de la source.

**Copie hors site.** `--copy-to [compte@]hôte:/chemin` (ou un chemin
absolu), désactivée par défaut : `rsync -a --partial` sur
`ssh -o BatchMode=yes`, sous le compte de l'unité, donc avec sa clé ssh et
son `known_hosts`. Une copie en échec garde la sauvegarde locale, est notée
et finit en code 1. La rétention ne s'applique pas côté distant : il
grossit.

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
[doc/PRODUCTION.fr.md](../../doc/PRODUCTION.fr.md).
