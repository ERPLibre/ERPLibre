
# Outils d'instance Odoo

| Fichier | Ce qu'il fait |
|---------|---------------|
| `update_module.py` | met à jour des modules installés d'une instance servie par systemd : arrêter, sauvegarder, mettre à jour, relancer, vérifier |
| `log_check.py` | lit le journal d'une instance : traces, erreurs, requêtes SQL refusées, échecs d'envoi de courriel, à revoir (lecture seule) |
| `mail_retry.py` | liste les courriels sortants en échec d'une instance (lecture seule), puis remet en file ceux qu'on choisit par le shell d'Odoo |
| `health_check.py` | vérifie qu'une instance répond et n'expose rien de trop : page de connexion, `/web/health`, TLS, redirection HTTPS, HSTS, gestionnaire de bases, bus, robots.txt, DNS du courriel (lecture seule) |
| `warmup_http.py` | réveille le registre dès que le serveur écoute ; lancé par `run.sh`. `--deep` préchauffe les pages publiques, les paquets d'assets et, avec une clé d'API, les vues |
| `odoo_conf_check.py` | vérifie un fichier de configuration d'Odoo comme Odoo le lit à son prochain démarrage : clés répétées, commentaire après une valeur, types selon la version, limites de mémoire ; conseils de workers et de mémoire (lecture seule) |
| `migration/` | outils de migration, voir [migration/README.fr.md](migration/README.fr.md) |

## update_module.py

```bash
./script/odoo/update_module.py --module my_module_a --dry-run
sudo ./script/odoo/update_module.py --module 'my_module_*' --db demo_db
```

Aussi accessible depuis `make todo` : `TODO › Exécuter › Production › Mise
à jour`, qui lance d'abord la simulation et demande avant l'exécution
réelle.

Ce qu'il fait, dans l'ordre :

1. **Détection, rien d'arrêté.** L'unité est `--service`, sinon l'unité
   `erplibre…`/`odoo…` dont `WorkingDirectory` est ce checkout, sinon la
   seule active. Son compte, son dossier, sa ligne de commande et son
   environnement viennent de `systemctl show`. La configuration Odoo, la
   base (`--db`, sinon le `-d` de l'unité, sinon `db_name`), le port HTTP et
   les modules (motifs développés sur l'`addons_path`, seuls les dossiers
   portant un `__manifest__.py`) en sont déduits. Tout manque refuse avec
   le code 2. La configuration est relue comme Odoo la lira au redémarrage
   (voir `odoo_conf_check.py` plus bas, types de la version d'Odoo du
   `.odoo-version` de l'unité), avant de chercher la base : une clé
   répétée, un commentaire après une valeur typée ou de connexion, une
   valeur qu'optparse refuse ou une limite de mémoire écrite en Mo refusent
   avec le code 2, puisque l'unité arrêtée ne repartirait pas, ou ne
   servirait pas. Avec `--odoo-conf`, le fichier de l'unité, celui de la
   relance, est vérifié aussi. Les avertissements sont listés dans le plan.
2. **Root et verrou.** Root est exigé (sauf `--dry-run`) ; un verrou par
   base, partagé avec l'outil de sauvegarde, code 75 quand une autre mise à
   jour ou une sauvegarde le détient.
3. **Arrêt.** L'état d'avant se lit dans `ActiveState` ; sans réponse de
   systemctl, rien n'est arrêté (code 2). Après `systemctl stop`, l'unité
   doit être `inactive` ou `failed` (pas `deactivating`). Si le port répond
   encore, ou qu'un processus Odoo tourne sur la même base hors de
   l'unité, la mise à jour est refusée, sauf `--force`.
4. **Sauvegarde** (sauf `--no-backup`), après l'arrêt pour être cohérente :
   la sauvegarde vérifiée de
   [script/database/odoo_backup.py](../database/README.fr.md), appelée
   alors que la mise à jour tient déjà le verrou de la base. Elle s'écrit
   dans `--backup-dest/<base>/` (par défaut `/var/backups/erplibre`) et se
   note dans `--state-dir` (par défaut `/var/lib/erplibre-backup`). Avant
   tout arrêt, la détection vérifie que le compte de l'unité peut y écrire
   (les dossiers manquants sont créés pour lui), que la base se lit et que
   l'espace disque suffit ; sinon elle refuse avec le code 2. Elle ne copie
   pas hors site et n'applique pas de rétention : la sauvegarde planifiée
   s'en charge.
5. **Mise à jour** : la ligne de commande de l'unité suivie de `-c CONFIG
   -d BASE -u MODULES --stop-after-init --no-http --workers=0
   --max-cron-threads=0 --limit-memory-hard=0 --log-level=info`, sous le
   compte de l'unité — le `-c` répété garde la mise à jour sur le fichier
   lu par la détection et la sauvegarde (`--odoo-conf` compris). Odoo
   retient la dernière valeur d'une option : la limite de mémoire du
   serveur (2560 Mio par défaut) n'arrête pas une mise à jour lourde en
   cours de route, et son journal garde les lignes INFO. Échec sur un
   code non nul, sur `--timeout`, ou sur un enregistrement `ERROR`/`CRITICAL` dans sa sortie ou dans ce qui
   s'est ajouté au `logfile` configuré. Un enregistrement est la ligne
   d'en-tête et ses lignes de continuation (une trace) ; le rapport groupe
   les traces par leur exception finale, comme `log_check.py`.
   `--ignore-error REGEX`, cherché dans la ligne d'en-tête et dans
   l'exception finale, écarte des enregistrements connus.
6. **Relance**, si l'unité tournait : attente de `active` et du port
   (`--start-wait`), une requête HTTP, puis lecture du journal de l'unité et
   du `logfile` depuis le démarrage.
7. **Après une relance vérifiée**, verrou relâché : avec `--warmup-deep`,
   le préchauffage profond de `warmup_http.py` (pages publiques et paquets
   d'assets, sans clé), puis la vérification de santé de l'instance locale
   (`health_check.py`). Leurs constats s'affichent en ATTN au plus et ne
   changent jamais le code de sortie ; un Ctrl-C n'y arrête que l'étape.

L'unité n'est jamais modifiée : l'outil la lit et lance seulement
`systemctl stop` / `start`. Quoi qu'il arrive après l'arrêt — échec,
exception, Ctrl-C, SIGTERM —, une unité qui tournait est relancée. Rien
n'est restauré : l'outil ne remplace pas le code ; la sauvegarde sert à une
restauration décidée par une personne.

| Code | Sens |
|------|------|
| 0 | réussi (ou simulation) |
| 1 | mise à jour en échec, service relancé |
| 2 | refusé avant tout arrêt |
| 75 | une autre mise à jour ou sauvegarde de cette base est en cours |
| 130 | interrompu, service relancé |

Le journal de la mise à jour va dans `--log-dir` (par défaut
`/var/log/erplibre`, avec repli sur le dossier temporaire).

**Profil.** Les réglages durables d'une instance viennent de son profil de
production : `--profile FICHIER`, sinon `private/production/<unité>.json`
de ce checkout (l'unité de `--service`, sinon celle qui est détectée).
L'outil lit son groupe `update_module` (`timeout`, `start_wait`,
`ignore_error`, `log_dir`, `warmup_deep`, `verbose`), plus `instance.db`,
`backup.dest` et `backup.state_dir`. Les chemins doivent être absolus, et
un motif `ignore_error` qui trouve n'importe quelle ligne d'erreur ou
n'importe quel titre de trace (`ValueError: …`) est refusé (code 2). La
ligne de commande l'emporte sur chaque valeur, `--profile-unset NOM` en
retire une, `--no-profile` ignore le fichier. Un profil trouvé par l'unité
que ce compte ne peut pas ouvrir est ignoré avec un ATTN ; donné par
`--profile`, ou avec `--profile-required`, il est refusé. Les
modules, l'unité, le compte, la configuration, `--force`, `--no-backup` et
`--dry-run` ne s'y lisent jamais : une telle clé est ignorée avec un ATTN.
Le plan liste chaque valeur venue du profil, un motif `--ignore-error` par
ligne, avant toute commande simulée.

`--no-profile` rend l'abréviation `--no` ambiguë : argparse la refuse, il
faut écrire `--no-backup` en entier.

`--warmup-deep` reste anonyme et prend les réglages par défaut du
préchauffage : il ne lit pas le groupe `warmup` du profil (identifiant, clé
d'API, pages), et la vérification de santé ne lit pas
`health_check.timeout`.

## log_check.py

```bash
./script/odoo/log_check.py --since-last
./script/odoo/log_check.py --last 6
./script/odoo/log_check.py --since "2026-03-01 08:00" --until "2026-03-01 12:00"
./script/odoo/log_check.py --by-hour --days 7
./script/odoo/log_check.py --file /var/log/odoo/odoo.log --json
```

**Source.** L'unité est `--service`, sinon détectée comme pour
`update_module.py`. Quand sa configuration pose un `logfile`, Odoo y écrit
et c'est ce fichier qui est lu ; sinon `journalctl -u UNITÉ -o short-iso`,
lu au fil de l'eau avec un délai total `--timeout`. Une unité qui pose
`LogNamespace=` écrit dans le journal de ce namespace, que `journalctl -u`
seul ne voit pas : la propriété est lue par `systemctl show` et passe en
`--namespace=NOM` ; `--namespace NOM` la remplace. `--file` lit un fichier
donné, sans unité. Quand le compte ne peut pas lire la configuration, un
`--logfile` d'ExecStart est lu s'il y en a un, sinon le journal ; une lecture
du journal qui ne rend aucun enregistrement d'Odoo refuse alors (code 2,
conseil sudo) au lieu de dire qu'il n'y a rien à revoir.

**Fenêtre.** `--since-last` reprend après la dernière lecture : le curseur
du journal (`--after-cursor`), ou l'octet d'un fichier qui garde son inode et
n'a pas raccourci (sinon il est relu depuis le début, et le rapport le dit) ;
la première fois, les dernières 24 h. `--last HEURES`, `--since`/`--until`
(heure locale) et `--by-hour --days N` (7 par défaut, ajoute la matrice
heure × jour) ne touchent jamais l'état. Sans option de fenêtre : les
dernières 24 h.

**État.** `--state-dir/<unité>.json` (par défaut
`/var/lib/erplibre-logcheck`), `<unité>+<namespace>.json` pour le journal
d'un namespace, pour que deux journaux ne partagent jamais un curseur ; un
curseur retenu pour un autre namespace ne sert pas. Il est écrit seulement
après une lecture complète et
réussie, par un fichier temporaire puis un renommage ; un état qui est un
lien symbolique n'est ni lu ni remplacé. Quand le dossier n'est pas
inscriptible, le rapport s'affiche quand même et dit « position non
retenue ».

**Rapport.** (1) Traces Python groupées par leur ligne d'exception finale,
avec nombre, première et dernière heure et un exemple (`--full-trace` le
montre en entier) ; (2) autres enregistrements `ERROR`/`CRITICAL` groupés
par logger et message normalisé ; (3) requêtes SQL refusées
(`odoo.sql_db: bad query`) par table et raison PostgreSQL ; (4) échecs
d'envoi de courriel classés passagers ou PERMANENTS, avec le réglage d'Odoo
à vérifier ; (5) bruit connu compté à part : cartes source d'assets
périmés, conflits de sérialisation qu'Odoo rejoue, abonnements push à clé
VAPID périmée, plus `--ignore REGEX` (cherché dans la ligne d'en-tête et
l'exception finale, jamais dans les cadres de la trace). Seuls `ERROR` et
`CRITICAL` sont « à revoir ». Les heures sont locales. `--json` donne un
résumé aux clés anglaises stables ; `update_module.py` emploie le même
analyseur.

**Profil.** Le groupe `log_check` d'un profil de production
(`private/production/<unité>.json`, ou `--profile FICHIER`) donne les
valeurs par défaut de `--namespace`, `--days`, `--ignore`, `--state-dir`
(chemin absolu), `--full-trace`, `--top`, `--timeout` et `--verbose`. Le
profil lu est celui de l'unité nommée par `--service` ou de l'unité
détectée ; `--file` ne lit aucun profil d'unité et écarte le `namespace`
d'un profil explicite. La ligne de commande gagne toujours : un `--ignore`
tapé remplace les motifs du profil au lieu de s'y ajouter. `--no-profile`
ignore le profil, `--profile-unset top` en retire une valeur. La fenêtre,
`--file`, `--until` et `--json` ne viennent jamais d'un profil. Le rapport
texte nomme le profil et liste chaque valeur reprise, marquée « (profil) » ;
`--json` ajoute une clé `profile` (`path`, `values`, `ignored`) et écrit les
avertissements sur stderr.

Il n'écrit rien d'autre que son fichier d'état et ne lit aucune base. Root
n'est pas exigé quand le compte est membre de `systemd-journal` (ou `adm`) ;
sinon journalctl ne montre que les messages du compte, ce qui est détecté et
signalé en code 2 avec le conseil de passer par sudo.

| Code | Sens |
|------|------|
| 0 | rien à revoir |
| 1 | quelque chose à revoir |
| 2 | lecture impossible (droits, unité, fichier, options) |
| 130 | interrompu |

## mail_retry.py

```bash
./script/odoo/mail_retry.py --dry-run
sudo ./script/odoo/mail_retry.py
sudo ./script/odoo/mail_retry.py --resend oldest 10 --yes
sudo ./script/odoo/mail_retry.py --resend ids 7404,7405 --yes --json
```

**Liste, en lecture seule.** Une requête `psql` sous le compte de l'unité,
les paramètres de connexion de sa configuration Odoo passés par
l'environnement et une transaction en lecture seule forcée par
`PGOPTIONS` : les `mail.mail` à l'état `exception` créés dans les `--days`
derniers jours (30), du plus ancien au plus récent, avec date, sujet,
destinataires masqués par défaut (`j***@example.org`, un nom affiché réduit
à son initiale ; `--details` montre tout) et la cause de l'échec, passagère
ou PERMANENTE, dont les adresses sont masquées de même, au texte comme en
`--json`. Puis les totaux par sujet, cause et jour, et les
avertissements : une cause PERMANENTE échoue de nouveau tant que le réglage
nommé n'est pas corrigé. Un refus par la limite de messages par session du
serveur SMTP (452 4.4.5, puis 503 Multiple MAIL) donne le plus grand groupe
de destinataires de ces courriels (« au moins N » quand une liste de
destinataires est coupée à 300 caractères) et la valeur de
`mail.session.batch.size` : une session porte jusqu'à autant de courriels
(1000 sans le paramètre) et un message par destinataire de chacun, donc le
serveur en compte la somme. Baisser `mail.session.batch.size` pour que,
multiplié par le plus grand groupe, il reste sous la limite, ou relever la
limite du serveur quand le groupe d'un seul courriel la dépasse ; un renvoi
fait avant échoue de nouveau et peut envoyer deux fois aux premiers
destinataires. Plus de 10 courriels avec `mail.session.batch.size` absent
ou au-dessus de 20 risquent la même limite.

**Renvoi, par l'ORM.** `--resend all | oldest N | ids LISTE` avec `--yes`
(sans terminal, rien n'est renvoyé sans lui) ; sur un terminal sans
`--resend`, un menu : `[a]` tous, `[o]` les plus anciens, `[i]` des ids,
`[n]` aucun (par défaut). `--list` ne fait que lister. Le
`odoo_bin.sh shell` de l'unité tourne sous son compte dans son dossier de
travail, avec un court script sur son entrée standard : il relit les
courriels encore en `exception`, appelle `action_retry()` quand la méthode
existe, sinon `write({'state': 'outgoing'})`, valide, et rend son bilan en
JSON. L'action planifiée « Mail: Email Queue Manager » envoie ensuite la
file. Aucune écriture SQL n'est jamais faite. `--dry-run` montre la
sélection, la commande et le script exacts. Au-delà de `--timeout`, tout le
groupe de processus du shell est arrêté ; une validation a pu précéder
l'arrêt, l'outil dit donc que l'issue est inconnue et qu'il faut relister.

**Profil.** `--days`, `--timeout`, `--verbose` et la base peuvent venir du
profil JSON de l'instance, `private/production/<service>.json` (groupe
`mail_retry`, base dans `instance.db`), ou de `--profile FICHIER` ; la ligne
de commande gagne toujours, `--profile-unset days` retire une valeur et
`--no-profile` ignore le fichier. `--details`, `--resend`, `--yes`,
`--list`, `--dry-run` et `--json` n'y sont jamais lus : une clé du profil
qui en nomme un est ignorée avec un ATTN. Avec `--resend`, le `days` du
profil est écarté : un renvoi choisit dans la liste de la fenêtre par
défaut ou d'un `--days` tapé sur la ligne de commande. La sortie texte liste chaque
valeur tirée du profil (`--days 14 (profile)`) avant toute commande ;
`--json` ajoute une clé `"profile"` (chemin, valeurs brutes, clés ignorées)
et écrit les avertissements sur stderr.

```json
{"version": 1, "service": "odoo-exemple.service",
 "instance": {"db": "exemple_db"}, "mail_retry": {"days": 14}}
```

Root n'est nécessaire que pour devenir le compte de l'unité.

| Code | Sens |
|------|------|
| 0 | aucun courriel en échec, ou tous les courriels choisis remis en file |
| 1 | des échecs listés et non renvoyés, ou une partie de la sélection ignorée |
| 2 | refusé ou impossible (détection, droits, psql, shell sans réponse) |
| 130 | interrompu |

### Odoo 12 à 18

| Point | Variation |
|-------|-----------|
| Ligne de journal | `date heure,ms pid NIVEAU base logger: message`, suivie de `perf_info` depuis 13 ; base `?` hors requête ; heure de l'en-tête en UTC |
| `mail.mail.failure_type` | présent en 18 ; non vérifié de 12 à 17 ; lu sans branchement (`to_jsonb(m)->>'failure_type'`), le texte décide quand il manque |
| `mail.mail.action_retry()` | vérifié en 18 seulement ; repli `write({'state': 'outgoing'})` |
| Filtre « De » (`from_filter`) | 15+ ; nommé dans le conseil sur l'expéditeur à partir de 15 |
| Domaines d'alias (expéditeur par défaut, catchall) | 17+ ; paramètres système `mail.default.from` et `mail.catchall.domain` jusqu'à 16 |
| `mail.session.batch.size` | présent en 18 ; non vérifié de 12 à 14 |

## health_check.py

```bash
./script/odoo/health_check.py --url https://odoo.example.org
./script/odoo/health_check.py --url odoo.example.org --mail-domain example.org --dkim-selector s1
./script/odoo/health_check.py --local --json
```

Il vérifie une instance Odoo, servie par systemd ou publiée à une URL. Ce
n'est pas le **Bilan de santé** (Healthcheck) de TODO, entrée propre du
menu principal (`TODO › Bilan de santé`), qui vérifie le checkout ERPLibre — dépôts, venvs, hooks —
et ne touche à aucune instance. Dans `make todo` : `TODO › Exécuter ›
Production › Santé et préchauffage`.

`--url` (répétable ; un hôte nu veut dire `https://hote`) sonde à travers
le proxy inverse ; `--local` (avec `--service`, sinon l'unité détectée)
sonde l'adresse que donne la configuration de l'unité, avec `?db=` quand la
base est connue. Une URL qui porte un identifiant (`compte:mdp@`) ou un
autre schéma que http(s) est refusée. Lecture seule : des GET, et un appel
JSON-RPC sans authentification à `/web/webclient/version_info` pour la
version. Aucun cookie, aucun en-tête `Authorization`, aucun proxy de
l'environnement, corps lus jusqu'à 1 Mio, `--timeout` (10 s) sur chaque
requête, connexion TLS et recherche DNS.

| Vérification | OK | ATTN | FAIL | SKIP |
|--------------|----|------|------|------|
| `http_login` | 200 en moins de 5 s | lente, redirection vers le sélecteur de bases, vers HTTP clair ou un autre hôte | aucune réponse, 5xx, autre statut | |
| `web_health` | 200 `pass` | réponse inattendue | aucune réponse, 5xx, `fail` | 404 (route absente) |
| `tls_certificate` | 21 jours ou plus | moins de 21 jours | moins de 7 jours, expiré, refusé (nom, chaîne, autosigné) | URL http, `--local` |
| `http_redirect` | `http://hote/` redirige vers https sur le même hôte | autre hôte, port 80 fermé, autre statut | servi en clair | URL http, `--local` |
| `hsts` | `max-age` ≥ 1 jour | absent, plus court | | pas de 200 sur `/web/login`, URL http, `--local` |
| `db_manager`, `db_selector` | bloqué (401/403/404/3xx), page « disabled » (`list_db = False`) | indéterminé (5xx) ; exposé en `--local` ; sélecteur qui liste les bases | gestionnaire joignable, ou mot de passe maître absent, en `--url` | |
| `list_db` (`--local`) | `False` | absent ou vrai | | |
| `odoo_conf` (`--local`) | lu sans erreur | un avertissement (commentaire après une valeur texte, limite douce au-dessus de la dure, ancien nom) | Odoo refuse le fichier à son prochain démarrage, ou ne peut pas servir avec lui | |
| `websocket` (`--url`) | relayé (400/426) | 404, aucune réponse | 502/503/504 | `--local` |
| `robots` (`--url`) | servi, ou `Disallow: /` sans ligne `Sitemap:` (pas de site public) | `Disallow: /` avec une ligne `Sitemap:` (l'URL employée n'est pas le domaine du site) | | 404 |
| `mail_spf` | un enregistrement fini par `-all`/`~all` | autre fin | aucun, plusieurs, `+all` | ni dig ni host, recherche en échec |
| `mail_dmarc` | présent (politique affichée) | absent | | ni dig ni host, recherche en échec |
| `mail_dkim` (`--dkim-selector`) | clé trouvée | | absente, clé vide | ni dig ni host, recherche en échec |

Le certificat n'est jugé que par `tls_certificate` : les autres requêtes
HTTPS ne le vérifient pas, pour qu'un certificat refusé donne un seul FAIL
et que les autres vérifications répondent encore. Une `--url` en HTTP clair
ajoute un ATTN `https`. Le DNS passe par `dig` ou `host`, domaine et
sélecteur validés d'abord (pas de `-` en tête) ; une recherche en échec est
un SKIP, jamais « enregistrement absent ». dig rend 0 pour toute réponse,
SERVFAIL et REFUSED compris : le statut de l'en-tête de sa réponse
tranche, et seuls NOERROR et NXDOMAIN sont définitifs. Aucun service web
tiers n'est contacté.

Un déploiement par défaut obtient un FAIL sur `db_manager` par `--url` :
Odoo garde `list_db = True` quand la configuration ne le pose pas, et les
gabarits nginx ne bloquent pas `/web/database`. Poser `list_db = False`, ou
refuser `/web/database` dans nginx.

Le conseil de `hsts` renvoie à `script/nginx/template_nginx_ssl_odoo_18.0.txt`,
le gabarit nginx du dépôt pour Odoo 18, dont les blocs `location` envoient
l'en-tête.

Clés de `--json` (anglais, stables) : `tool`, `odoo_version`, `targets`
(`kind`, `url`, `odoo_version`), `checks` (`id`, `target`, `status`,
`message`, `hint`, `data`), `summary` (`ok`, `attn`, `fail`, `skip`),
`exit_code`.

**Profil.** Le groupe `health_check` d'un profil de production donne
`--url` (une liste), `--mail-domain`, `--dkim-selector`, `--timeout` et
`--verbose`. Avec `--local`, le profil lu est celui de l'unité que nomme
`--service`, ou de l'unité détectée ; sans `--local`, seul `--profile
FICHIER` en apporte un, dont les URL sont sondées sans nommer de service.
Un `dkim_selector` sans `mail_domain` effectif est écarté avec un ATTN. La
ligne de commande gagne toujours : une `--url` tapée remplace toute la
liste du profil. `--no-profile` ignore le profil, `--profile-unset url` en
retire une valeur. `--local`, `--service` et `--json` ne viennent jamais
d'un profil. Le rapport texte nomme le profil et liste chaque valeur qu'il
en a prise, marquée « (profil) », avant la première sonde ; `--json` ajoute
une clé `profile` (`path`, `values`, `ignored`) et écrit les
avertissements sur stderr.

| Code | Sens |
|------|------|
| 0 | aucun FAIL (les ATTN sont listés) |
| 1 | au moins un FAIL |
| 2 | vérification impossible (usage, détection, configuration illisible : lancer avec sudo) |
| 130 | interrompu |

## odoo_conf_check.py

```bash
./script/odoo/odoo_conf_check.py
./script/odoo/odoo_conf_check.py --file /etc/odoo/odoo.conf --odoo-version 16
./script/odoo/odoo_conf_check.py --service odoo-exemple --json
```

Odoo n'a pas de commande qui vérifie seulement son fichier de
configuration : une erreur se voit au démarrage, c'est-à-dire après un
`systemctl stop`. Cet outil lit le fichier de `--file`, sinon celui que lit
l'unité systemd (`--service`, sinon l'unité détectée, comme la trouve
`update_module.py`), avec les règles d'Odoo lui-même, et ne change rien.
Dans `make todo` : `TODO › Exécuter › Production › Santé et préchauffage ›
Valider odoo.conf`.

| Niveau | Constat |
|--------|---------|
| erreur | clé ou section donnée deux fois, ligne hors de toute section ou sans `=` (`configparser` strict refuse tout le fichier) ; une option typée (`workers`, ports, `limit_*`…) ou à choix (`log_level`, `db_sslmode`) dont optparse refuse la valeur, commentaire après elle compris (`workers = 4 # quatre` garde `# quatre` dans la valeur) ; un commentaire après une valeur de connexion ou d'écoute (`db_host`, `db_user`, `db_name`, `db_replica_host`, `http_interface`), passée telle quelle à PostgreSQL ou au socket ; une limite de mémoire sous 100000 (des octets, voulus en Mo) |
| avertissement | aucune section `[options]` (Odoo démarre avec ses valeurs par défaut) ; commentaire après une autre valeur texte ; `limit_memory_soft` au-dessus de `limit_memory_hard` ; `limit_memory_soft` sous 1024 Mo avec des workers (16 et suivantes) ; `longpolling_port` dès la 17 (ignoré, le bus écoute sur `gevent_port`) ; un ancien nom (`xmlrpc_port`) et son nouveau nom posés tous les deux à des valeurs différentes ; trop de workers pour les processeurs, ou pour la mémoire |
| info | ancien nom (`xmlrpc_port`, lu comme `http_port`) ; limites `gevent` non posées (18) ; `workers = 0` ; `limit_memory_soft`/`limit_memory_hard` conseillés |

Seule une ligne qui COMMENCE par `#` ou `;` est un commentaire.
`True`/`true` et `False`/`false` sont des booléens ; toute autre valeur
d'une option typée passe par optparse (`0x10` et `-1` passent, `08` et
`2048MB` non). La valeur d'une clé qui ressemble à un secret
(`admin_passwd`, `db_password`, `sentry_dsn`…) n'est jamais citée, ni le
compte et le mot de passe d'une adresse (`schéma://compte:mot@hôte`),
quelle que soit la clé.

Les types suivent la version d'Odoo : `--odoo-version`, sinon le
`.odoo-version` du dossier de l'unité (ou du dossier du fichier avec
`--file`), sinon un chemin `odooNN.0` de la ligne de commande de l'unité ;
inconnue, seuls les types communs aux versions 12 à 18 sont vérifiés. Les
conseils de workers et de mémoire suivent le guide de déploiement d'Odoo —
au plus (2 × CPU) + 1 workers, 150 Mo par worker léger et 1 Gio par lourd
— avec les processeurs et la mémoire de `--cpus` et `--memory-mb`, sinon
de ce poste (les limites d'un cgroup ne sont pas lues). Les limites
conseillées gardent 15 % de la mémoire pour le reste du poste et une marge
de 10 %, et ne mettent jamais `limit_memory_soft` sous 1050 Mo.

La même validation tourne dans `update_module.py` avant tout arrêt (une
erreur refuse, code 2) et dans `health_check.py --local` (résultat
`odoo_conf`).

**Profil.** Le groupe `odoo_conf` donne `--cpus`, `--memory-mb` et
`--verbose`. `--file`, `--service`, `--odoo-version` et `--json` ne
viennent jamais d'un profil. Avec `--file`, l'unité n'est pas devinée :
seul `--profile` apporte un profil.

Clés de `--json` (anglais, stables) : `tool`, `service`, `path`,
`odoo_version`, `findings` (`level`, `line`, `key`, `code`, `message`),
`summary` (`error`, `warning`, `info`), `host` (`cpus`, `memory_mb`),
`exit_code`.

| Code | Sens |
|------|------|
| 0 | aucune erreur (les avertissements sont listés) |
| 1 | au moins une erreur : Odoo refuse le fichier à son prochain démarrage, ou ne peut pas servir avec lui |
| 2 | vérification impossible (usage, détection, fichier illisible : lancer avec sudo) |
| 130 | interrompu |

## warmup_http.py --deep

```bash
./script/odoo/warmup_http.py --deep --local
./script/odoo/warmup_http.py --deep --url https://odoo.example.org -d BASE --max-pages 50
./script/odoo/warmup_http.py --deep --local --login admin --api-key-file ~/.odoo_key --models res.partner,sale.order
```

Sans `--deep`, rien ne change : une ligne, muet avec `--quiet`, toujours le
code 0, options inconnues transmises à Odoo ; un `--deep` placé après `--`
appartient à Odoo. Avec `--deep` : attente de la première réponse
(`--timeout`, 120 s), puis travail par `--repeat` (4, 16 au plus) voies,
chacune avec ses cookies et sa propre session ouverte sur
`/web/login?db=BASE` : deux requêtes d'une même session ne partent jamais
en même temps (Odoo 16+ tire le visiteur anonyme de l'IP, de l'User-Agent
et de la session, et des requêtes simultanées d'une même session
upserteraient la même ligne `website_visitor`, journalisé en ERROR).
`/web/login`, `/` et au plus `--max-pages` (20) pages HTML de
`/sitemap.xml` (un index est suivi d'un cran ; seul le chemin de chaque
`<loc>` est gardé, la requête part vers la cible), puis chaque paquet
d'assets que ces pages citent (`/web/assets/…`, et `/web/content/…assets_…`
des versions anciennes). Chaque page ou paquet est demandé une fois seul
par la première voie — ce premier rendu compile les gabarits ou construit
le paquet —, puis une fois par chacune des autres voies, à la fois ; ce
qui échoue à la première requête n'est pas répété. Avec `--login` et
`--api-key-file` : `common.login` par `/jsonrpc` avec la clé d'API (Odoo
n'accepte une clé que hors d'une connexion interactive), puis
`execute_kw` d'une liste fermée de méthodes de lecture, chacune une fois
par voie, à la fois : `res.users.context_get`, `ir.ui.menu.load_menus` et, pour chaque modèle de
`--models` (`res.partner`), `get_views` (16+) ou `load_views` (15 et avant).
Le fichier de la clé est lu sans suivre de lien ; un fichier lisible par
d'autres comptes reçoit un avertissement. La clé ne part qu'en https, ou
en http vers la boucle locale (`--local`, l'adresse du mode par défaut) :
`--login` avec une URL `http://` sur un autre hôte est refusé (code 2). La
cible est `--url`, `--local` (unité détectée) ou l'adresse du mode par
défaut. Un `<loc>` du sitemap qui n'est ni une URL absolue ni un chemin
commençant par `/` est ignoré : seul son chemin part, vers la cible.

**Profil** (`--deep` seulement). Le groupe `warmup` d'un profil de
production (`private/production/<unité>.json`, ou `--profile FICHIER`)
donne les valeurs par défaut de `--timeout`, `--max-pages`, `--repeat`,
`--login`, `--api-key-file` (chemin absolu ; une référence KeePass
`{"kdbx": …}` n'est jamais lue par l'outil), `--models` (virgules, comme
sur la ligne de commande) et `--strict` ; la base vient de `instance.db`.
Le profil de l'unité n'est lu qu'avec `--local` : celle que nomme
`--service`, ou l'unité détectée, devinée une seule fois pour le profil
et pour la cible. Avec un `--profile` explicite et `--local`, l'unité est
le `service` du profil ; `--url` et l'adresse du mode par défaut ne lisent
aucun profil d'unité. `--login` et `--api-key-file` vont ensemble : l'un
sans l'autre est écarté, comme `--login` quand la clé d'API est une
référence KeePass. La cible (`--url`, `--local`), `--service` et les options
du mode par défaut (`-c`, `--log`, `--quiet`, arguments d'Odoo) ne
viennent jamais d'un profil. La ligne de commande gagne toujours,
`--profile-unset repeat` retire une valeur, `--no-profile` ignore le
fichier. Une ligne `🔧 profile: <chemin> (<n>)` vient d'abord, puis
chaque valeur retenue, marquée « (profil) », et un `[ATTN]` par valeur
écartée. **Le mode par défaut (celui de `run.sh`) ne lit jamais de
profil** : il reste muet et rend toujours 0, même à côté d'un profil
invalide.

Une requête échoue sur une absence de réponse ou un code ≥ 500, et sur une
erreur JSON-RPC ; un 4xx est compté à part (« non public »). Aucune
requête, la sonde du mode par défaut comprise, ne passe par le proxy de
l'environnement (`http_proxy`).

| Code | Sens |
|------|------|
| 0 | fait, échecs compris |
| 1 | avec `--strict`, au moins un échec |
| 2 | option invalide, fichier de clé illisible, pas de base avec `--login`, profil invalide |
| 130 | interrompu |

### Odoo 12 à 18 (santé, préchauffage)

| Point | Variation |
|-------|-----------|
| `/web/health` | 18 : présent, `db_server_status=1` vérifie PostgreSQL ; 16 et 17 : présent (non vérifié) ; 12 à 15 : absent, SKIP |
| Chemin du bus derrière le proxy | `/websocket` dès 16 (vérifié en 18) ; `/longpolling/poll` jusqu'à 15 ; une version inconnue essaie les deux |
| URL du client web | `/odoo` en 18, `/web` y redirige ; `/web` jusqu'à 17 |
| Chargement des vues par RPC | `get_views` dès 16, `load_views` jusqu'à 15 ; type de vue liste `list` en 18, `tree` avant |
| Clé d'API avec `common.login` | 14+ (hors connexion interactive seulement) ; aucune en 12 et 13 |
| `/robots.txt` | sans website, 18 : `Disallow: /` et des lignes `Allow:`, 404 jusqu'à 17 (non vérifié) ; avec website : une ligne `Sitemap:`, et `Disallow: /` quand l'URL n'est pas le domaine du site (vérifié en 18) |
| Gestionnaire de bases avec `list_db = False` | 18 : 200 avec la page « disabled » (le corps est lu, pas seulement le statut) ; non vérifié de 12 à 17, un 403 est traité aussi |
| Gabarits nginx d'ERPLibre | pas de HSTS de 12 à 15 ; HSTS dans `location /` dès 16 ; aucun ne bloque `/web/database` |
| Options typées d'`odoo.conf` (`odoo_conf_check.py`) | communes de 12 à 18 : `http_port`, `db_port`, `smtp_port`, `workers`, `max_cron_threads`, `limit_memory_soft`/`hard`, `limit_time_*`, `limit_request`, `db_maxconn` ; `longpolling_port` de 12 à 16, ignoré dès 17 ; `gevent_port` dès 16 ; `osv_memory_age_limit` jusqu'à 17 ; `transient_age_limit` dès 14 ; les limites de mémoire `gevent`, `db_replica_port`, `db_maxconn_gevent` et `limit_time_worker_cron` en 18 |