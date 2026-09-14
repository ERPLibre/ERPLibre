<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Changelog
<!-- [fr] -->
# Journal des modifications
<!-- [en] -->

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com). This project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- [fr] -->

Tous les changements notables de ce projet seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com). Ce projet adhère
au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- [common] -->

## [Unreleased]

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Site presets for the VPN: one `.json` carries a site's gateway, protocol and connection group, and neither a username nor a secret, so it can be handed around. Read from `conf/vpn_presets/`, then from a git-ignored `private/vpn/presets/`, then from any directory listed in `vpn_preset_paths`; on the same identifier the latest wins, so a site fixes a shipped template without touching a tracked file
- Import a Cisco AnyConnect `.xml` profile from the menu, browsing the client's own directories or typing the path, and get a preset from its `HostName`, `HostAddress` and `UserGroup`
- OpenConnect tells apart the two mechanisms that designate a service on one concentrator: the connection group in the URL and the value picked from a dropdown. Confusing them hands over another service's login form, so correct credentials are refused with nothing naming the group
- Reach a gateway that demands an embedded browser for SAML, which stops OpenConnect on « No SSO handler »: the web step is delegated to an `openconnect-sso` helper that the installer offers to set up, and the tunnel is then brought up by the driver itself, so the interface name, the state files and the diagnosis stay with the profile
- Declare a concentrator that compares only the first characters of a password: it is announced before the secret is stored, and nothing is ever truncated
- The VPN installer looks for `vpnc-script` — a file, not a binary on the `PATH` — and names the package to install per distribution family, instead of letting the tunnel fail on an interface that never appears
- A command launched by the VPN runner gets `/dev/null` on standard input, so a captured-output command can no longer be stopped by a SIGTTOU and freeze the machine's package manager
- The VPN profile list marks which profiles carry a live tunnel, so connecting one already up asks first and disconnecting one already down says so instead of looking like a mistake. A profile is judged on its interface, not on the state file a tunnel killed without `down` leaves behind — a state left over used to be reported as mounted on the same screen that declared the process gone
- `Assistant › LLM` — ask a model server over several turns, local or remote. The history lives in memory and dies with the menu, `/save` being the only way to keep a trace; every command carries a leading slash, so a question pasted over several lines stays one turn. A third-party destination has to be retyped before the first send
- Server recognition across eleven ports and twelve families, identity read from the response BODY and never from the port: one port hosts up to three products, and one family re-serves another's whole native API
- Finding a server from six sources — the loopback, this machine's QEMU domains, the hosts of `~/.ssh/config`, an address or a network typed by hand, and the networks read over SSH on another machine. Anything wider than a `/24` is refused before enumeration, and two preferences bound the sweep: `assistant_sweep_workers`, `assistant_sweep_timeout`
- A gpt catalogue in `script/todo/assistant/gpt/`: one Markdown file per tool, whose declared requirements are matched against what the server announces. An unknown never greys a tool out — only a requirement contradicted by a field actually read does, with the figure that refuses it
- A declared READ-ONLY context per tool, files and allowlisted commands, shown and confirmed before the first send, capped in size and duration, and scanned for identifying data. The scan's honest limit is stated: it sees addresses, e-mails and account paths, not names
- `Execute › GPT code › Claude Code` — list the machine's sessions, ask one a question with read-only tools, or resume one in its own terminal. A copy is branched by default, since two writers on one session lose a branch
- `check_comment_hygiene.py` signals a fully qualified machine name in a comment, as a re-read signal and never a finding: a BARE host name is mechanically indistinguishable from an ordinary word, so the absence of a signal proves nothing about names. The copyright header, the RFC 2606 domains and any address carried by a URL are left alone
- Transform data, a menu entry that opens an external file — Excel, Access, CSV, XML or JSON — reports what it holds, then draws an anonymised copy of it. The original is never touched. Numbers are drawn from the measured extent of their own column rather than a fixed 0-1000 range, which turns a tax rate into 743 and a year into 12; they are drawn without replacement, since a hundred distinct keys in a range of a hundred otherwise yield sixty-six outputs and a fixture that no longer reimports. Text takes a French word from a local dictionary of 1366, assigned by a counter rather than a draw, and a portable mapping table gives the same client the same word across a whole batch
- Eleven structural labels are left alone on their NAME — `id`, `create_uid`, `sequence`, `active` and the rest, plus anything ending in `/id` or `/.id` — since a test set has to keep working. Every OTHER column is judged on its measured CONTENT, never on the strength of its name. In an import-ready export, `partner_id` holds the relation's display name and `display_name` is the data itself, so deciding on the label copied the most identifying columns of the file verbatim while announcing them as protected
- The anonymiser rereads the bytes it has just written and refuses the copy when a value it announced as replaced survives in it. A workbook holds data in a dozen places that are not cells: a pivot cache and an external link each carry an entire copy of the source, a chart caches its categories and its axis titles, a custom number format carries a label, a comment carries its author, a cell hyperlink carries a path. The guard depends on no list of those, so a place nobody thought to clean produces a refusal instead of a silence — and what stays by decision, a header row or a column left alone, is named on screen before anything is written
- Transform data anonymises an Odoo database too, the entry asking for the SOURCE rather than the format: an external file, a live database, or a backup zip taken from `image_db/`. A zip is never modified — it is restored into a database, anonymised there, then dumped into a NEW zip by Odoo's own backup, so the dump, the filestore and the manifest are written by the software that will read them back. A live database is modified ITSELF, which is said before the work and not after, and nothing is drawn when the write did not happen: declining otherwise handed back a zip of the untouched database, announced as anonymised. A register records which databases the entry produced, since the server does not
- An anonymised number can keep its digit count, on the file anonymiser and on `anonymize.py` alike (`--keep-digits`): 8839 then draws in 1000..9999, so the copy keeps columns of the same width, which an export read by eye or imported into a bounded field asks for. Each value keeps ITS own width and not its column's — 7 stays at one digit where 12 keeps two — and below the unit the rule does not apply, 0.15 having no digit before the point. The option trades one guarantee for another: the measured extent no longer bounds anything, so a rate or a year can leave its range, and the preview SAYS so rather than letting it be found at reimport. Uniqueness is what yields when a band fills up, a duplicate of the same width beating a value of a different one, and the band never exceeds what the type RECEIVING the draw holds, which is not always the column's: an Odoo `integer` over a column PostgreSQL did not create as an integer — what an upgraded base carries — is poured into `numeric`, which has no ceiling, where `integer` stops at 2 147 483 647 and a draw past it aborts the whole write, that write being one transaction
- The anonymiser asks four questions instead of eleven, seven of the eleven having had an obvious default. Answering them one by one to arrive at the same place makes prompts be passed by reflex, and a prompt passed by reflex consents to nothing; they now live behind « Advanced options? ». The short path DECLARES what it takes, in sentences rather than in yes/no, since those are decisions taken and not questions whose answer was lost. Macros and charts are asked on both paths: they are not visible in the cells
- `markdown-it-py` is declared as a functional dependency: it renders the language model's markdown to HTML, before sanitising, on the assistant page. It reached the environment transitively through `bandit` → `rich`, a lint tool, so removing a lint dependency removed a portal page's rendering engine

<!-- [fr] -->

- Des préréglages de site pour le VPN : un `.json` porte la passerelle d'un site, son protocole et son groupe de connexion, et ni identifiant ni secret, si bien qu'il peut circuler. Lus depuis `conf/vpn_presets/`, puis depuis un `private/vpn/presets/` ignoré par git, puis depuis tout répertoire listé dans `vpn_preset_paths` ; sur un même identifiant le plus tardif gagne, et un site corrige un gabarit livré sans toucher de fichier suivi
- Importer un profil Cisco AnyConnect `.xml` depuis le menu, en parcourant les répertoires du client ou en tapant le chemin, et en tirer un préréglage de ses balises `HostName`, `HostAddress` et `UserGroup`
- OpenConnect distingue les deux mécanismes qui désignent un service sur un même concentrateur : le groupe de connexion dans l'URL et la valeur choisie dans un menu déroulant. Les confondre donne le formulaire d'un autre service, et des identifiants justes sont refusés sans que rien ne nomme le groupe
- Joindre une passerelle qui exige un navigateur intégré pour le SAML, ce qui arrête OpenConnect sur « No SSO handler » : l'étape web est déléguée à un greffon `openconnect-sso` que l'installateur propose de poser, et le tunnel est ensuite monté par le pilote lui-même, si bien que le nom d'interface, les fichiers d'état et le diagnostic restent au profil
- Déclarer un concentrateur qui ne compare que les premiers caractères d'un mot de passe : il est annoncé avant le dépôt du secret, et rien n'est jamais tronqué
- L'installateur VPN cherche `vpnc-script` — un fichier, et non un binaire du `PATH` — et nomme le paquet à poser par famille de distribution, au lieu de laisser le tunnel échouer sur une interface qui n'apparaît jamais
- Une commande lancée par l'exécuteur VPN reçoit `/dev/null` sur son entrée standard, si bien qu'une commande à sortie capturée ne peut plus être arrêtée par un SIGTTOU et figer le gestionnaire de paquets de la machine
- La liste des profils VPN marque ceux qui portent un tunnel vivant, si bien que connecter un profil déjà monté demande confirmation et que déconnecter un profil déjà tombé le dit au lieu de ressembler à une erreur. Un profil est jugé sur son interface et non sur le fichier d'état qu'un tunnel tué sans `down` laisse derrière lui — un état laissé était annoncé monté sur l'écran même qui déclarait le processus mort
- `Assistant › LLM` — interroger un serveur de modèle sur plusieurs tours, local ou distant. L'historique vit en mémoire et meurt avec le menu, `/save` étant le seul moyen d'en garder une trace ; toute commande porte une barre oblique initiale, donc une question collée sur plusieurs lignes reste un seul tour. Une destination tierce doit être retapée avant le premier envoi
- Reconnaissance du serveur sur onze ports et douze familles, l'identité étant lue dans le CORPS de la réponse et jamais dans le port : un port héberge jusqu'à trois produits, et une famille réémet l'API native d'une autre en entier
- Recherche d'un serveur depuis six sources — la boucle locale, les domaines QEMU de la machine, les hôtes de `~/.ssh/config`, une adresse ou un réseau saisi, et les réseaux lus en SSH sur une autre machine. Plus large qu'un `/24` est refusé avant énumération, et deux préférences bornent le balayage : `assistant_sweep_workers`, `assistant_sweep_timeout`
- Un catalogue d'outils gpt dans `script/todo/assistant/gpt/` : un fichier Markdown par outil, dont les exigences déclarées sont confrontées à ce que le serveur annonce. L'inconnu ne grise jamais un outil — seule une exigence contredite par un champ réellement lu le fait, avec le chiffre qui la refuse
- Un contexte LECTURE SEULE déclaré par outil, fichiers et commandes autorisées, montré et confirmé avant le premier envoi, borné en taille et en durée, et balayé à la recherche de données identifiantes. La limite du balayage est dite : il voit les adresses, les courriels et les chemins de compte, pas les noms
- `Exécution › GPT code › Claude Code` — lister les sessions de la machine, en interroger une avec des outils en lecture seule, ou la reprendre dans son propre terminal. Une copie est branchée par défaut, deux écritures sur une même session perdant une branche
- `check_comment_hygiene.py` signale un nom de machine pleinement qualifié dans un commentaire, en signal à relire et jamais en trouvaille : un nom d'hôte NU ne se distingue mécaniquement pas d'un mot ordinaire, donc l'absence de signal ne prouve rien sur les noms. L'en-tête de copyright, les domaines de la RFC 2606 et toute adresse portée par une URL sont laissés tranquilles
- Transform data, une entrée de menu qui ouvre un fichier externe — Excel, Access, CSV, XML ou JSON —, rapporte ce qu'il porte, puis en tire une copie anonymisée. L'original n'est jamais touché. Les nombres sont tirés dans l'étendue mesurée de leur propre colonne plutôt que dans un intervalle fixe de 0 à 1000, qui rend un taux de TVA à 743 et une année à 12 ; ils sont tirés sans remise, cent clés distinctes dans une étendue de cent ne rendant sinon que soixante-six sorties, et une fixture qui ne se réimporte plus. Le texte prend un mot français dans un dictionnaire local de 1366, attribué par un compteur et non par un tirage, et une table de correspondance portable donne au même client le même mot sur tout un lot
- Onze étiquettes structurelles sont laissées intactes sur leur NOM — `id`, `create_uid`, `sequence`, `active` et les autres, plus tout ce qui finit en `/id` ou `/.id` —, un jeu de test devant continuer de fonctionner. Toute AUTRE colonne est jugée sur son CONTENU mesuré, jamais sur la seule foi de son nom. Dans un export import-compatible, `partner_id` porte le nom affiché de la relation et `display_name` est la donnée elle-même : décider sur l'étiquette recopiait textuellement les colonnes les plus identifiantes du fichier en les annonçant comme protégées
- L'anonymiseur relit les octets qu'il vient d'écrire et refuse la copie dès qu'une valeur annoncée comme remplacée y subsiste. Un classeur porte de la donnée dans une douzaine d'endroits qui ne sont pas des cellules : un cache de tableau croisé et un lien externe en portent chacun une copie entière, un graphique met ses catégories et ses titres d'axes en cache, un format de nombre personnalisé porte un libellé, un commentaire porte son auteur, un hyperlien de cellule porte un chemin. Le filet ne dépend d'aucune liste de ces endroits, si bien qu'un endroit que personne n'a pensé à nettoyer produit un refus et non un silence — et ce qui reste par décision, une ligne d'en-tête ou une colonne laissée intacte, est nommé à l'écran avant que rien ne soit écrit
- Transform data anonymise aussi une base Odoo, l'entrée demandant la SOURCE plutôt que le format : un fichier externe, une base vivante, ou un zip de sauvegarde pris dans `image_db/`. Un zip n'est jamais modifié — il est restauré dans une base, anonymisé là, puis vidé dans un zip NEUF par la sauvegarde d'Odoo lui-même, si bien que le dump, le filestore et le manifeste sont écrits par le logiciel qui les relira. Une base vivante est modifiée ELLE-MÊME, ce qui est dit avant le travail et non après, et rien n'est tiré lorsque l'écriture n'a pas eu lieu : un renoncement rendait sinon un zip de la base intacte, annoncé comme anonymisé. Un registre inscrit les bases que l'entrée a produites, le serveur ne le disant pas
- Un nombre anonymisé peut garder son nombre de chiffres, sur l'anonymiseur de fichiers comme sur `anonymize.py` (`--keep-digits`) : 8839 tire alors dans 1000..9999, si bien que la copie garde des colonnes de la même largeur, ce qu'un export relu à l'œil ou importé dans un champ borné demande. Chaque valeur garde SA largeur et non celle de sa colonne — 7 reste à un chiffre là où 12 en garde deux — et sous l'unité la règle ne s'applique pas, 0,15 n'ayant pas de chiffre avant la virgule. L'option échange une garantie contre une autre : l'étendue mesurée ne borne plus rien, donc un taux ou une année peut sortir de sa plage, et l'aperçu le DIT au lieu de le laisser découvrir à la réimportation. C'est l'unicité qui cède quand une bande se remplit, un doublon de la même largeur valant mieux qu'une valeur d'une autre, et la bande ne dépasse jamais ce que tient le type qui ACCUEILLE le tirage, lequel n'est pas toujours celui de la colonne : un `integer` d'Odoo posé sur une colonne que PostgreSQL n'a pas créée entière — ce qu'une base montée de version porte — se coule en `numeric`, qui n'a pas de plafond, là où `integer` s'arrête à 2 147 483 647 et où un tirage au-delà fait retomber toute l'écriture, celle-ci tenant en une transaction
- L'anonymiseur pose quatre questions au lieu de onze, sept des onze ayant eu un défaut évident. Les répondre une par une pour arriver au même endroit fait passer les invites par réflexe, et une invite qu'on passe par réflexe ne consent à rien : elles vivent désormais derrière « Options avancées ? ». Le chemin court DIT ce qu'il prend, en phrases et non en oui/non, puisque ce sont des décisions prises et non des questions dont on aurait perdu la réponse. Macros et graphiques sont demandés dans les deux chemins : ils ne se voient pas dans les cellules
- `markdown-it-py` est déclaré en dépendance fonctionnelle : il rend en HTML le markdown du modèle de langage, avant assainissement, sur la page de l'assistant. Il arrivait dans l'environnement en transitif par `bandit` → `rich`, un outil de lint, si bien que retirer une dépendance de lint retirait le moteur de rendu d'une page portail

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- `Assistant › [1]` no longer sends every question to a single remote API on a fixed model: it asks whichever server is configured, and falls back to the remote one only when no local server answers

<!-- [fr] -->

- `Assistant › [1]` n'envoie plus chaque question à une seule API distante sur un modèle figé : elle interroge le serveur configuré, et ne retombe sur le distant que lorsqu'aucun serveur local ne répond

<!-- [en] -->
## Fixed
<!-- [fr] -->
## Corrigé
<!-- [en] -->

- Reading the dnsmasq leases no longer opens a root password prompt: the files are read directly, which suffices on a standard install where they are 0644, and only then is `sudo -n` tried, which fails instead of asking. Displaying a VM list called that path once per VM, and waiting on a VM called it every three seconds for ten minutes
- `--max_process` runs again on Python 3.10 and later: `loop=` left `asyncio.wait` in 3.10 and `asyncio.get_event_loop()` raises outside a running loop since 3.14, so the pool was not even constructible while the help still advertised the flag
- A prompt no longer writes its colon twice — the most-seen menu of the software asked « Command:: », and seven remote-deployment prompts showed a colon followed by another
- Eleven submenus now leave their segment in the breadcrumb, and navigation telemetry stops filing them as commands under their raw method name
- The three readers of `~/.ssh/config` agree on what a machine name is: an alias declared with a lowercase `host` is seen, a tab separates as legally as a space, and a negated `!name` pattern is no longer taken for a machine to connect to
- Three translation keys declared twice are gone, and a check refuses the next one: a repeated key silently overwrites the previous, which had already cost a menu label
- `anonymize.py` abstains from a unique numeric column and NAMES it in the report. A draw guarantees nothing on a unique column, and a number has no way out where text has one — appending the id carries uniqueness for text, but would change a number's magnitude. Two rows drawing the same number failed the UPDATE and, the whole run being one transaction, took the entire anonymisation with them. Without the report naming it, an identifying column stays in the clear with nothing saying so
- Restoring a backup no longer raises `AttributeError` before running the command: `_monitoring_restore` read `self._execute` where `TODO` sets `self.execute`, and both entries leading there — the local backup and the remote one — were broken. A check refuses the next one: every `self.X` that `TODO` READS must be set by TODO or by one of its bases. Searching the name across `script/todo/` did not see the fault, another object of the package setting `_execute`; it has to be searched in the classes TODO INHERITS from
- The Selenium scripts run on a Python built without `tkinter` — any server with no graphical toolkit package. That module is only needed by the vault's file picker, so it is now optional: with no `tkinter` and no configured KDBX path, opening the vault logs an error and returns, instead of breaking the import of every browser-automation script
- Dark mode works again in a private window on a current Firefox. The « Run in Private Windows » permission is granted when the addon is installed, through the `allowPrivateBrowsing` field, rather than clicked through the `about:addons` interface: Firefox refuses navigation to `about:addons` from the content context, and the chrome context demands `-remote-allow-system-access`, which geckodriver rejects through capabilities, so both routes to that checkbox are closed. A geckodriver that ignores the field installs without the permission instead of killing the session

<!-- [fr] -->

- La lecture des baux dnsmasq n'ouvre plus d'invite de mot de passe root : les fichiers sont lus en direct, ce qui suffit sur une installation standard où ils sont en 0644, et `sudo -n` n'est tenté qu'ensuite, qui échoue au lieu de demander. L'affichage d'une liste de VM appelait ce chemin une fois par VM, et l'attente d'une VM toutes les trois secondes pendant dix minutes
- `--max_process` repart sur Python 3.10 et plus : `loop=` a quitté `asyncio.wait` en 3.10 et `asyncio.get_event_loop()` lève hors d'une loop en marche depuis 3.14, si bien que le pool n'était même plus instanciable alors que l'aide annonçait toujours l'option
- Une invite n'écrit plus son deux-points deux fois — le menu le plus vu du logiciel demandait « Commande :: », et sept invites de déploiement à distance affichaient un deux-points suivi d'un autre
- Onze sous-menus laissent désormais leur segment dans le fil d'Ariane, et la télémétrie de navigation cesse de les classer comme des commandes sous leur nom de méthode brut
- Les trois lecteurs de `~/.ssh/config` s'accordent sur ce qu'est un nom de machine : un alias déclaré par un `host` en minuscules est vu, une tabulation sépare aussi légalement qu'un espace, et un motif nié `!nom` n'est plus pris pour une machine à joindre
- Trois clés de traduction déclarées deux fois ont disparu, et un contrôle refuse la suivante : une clé répétée écrase la précédente en silence, ce qui avait déjà coûté une étiquette de menu
- `anonymize.py` s'abstient sur une colonne numérique unique et la NOMME dans le rapport. Un tirage ne garantit rien sur une colonne unique, et un nombre n'a pas l'issue qu'a le texte — coller l'id porte l'unicité pour du texte, mais changerait la grandeur d'un nombre. Deux lignes tirant le même nombre faisaient échouer l'UPDATE et, transaction unique oblige, emportaient TOUTE l'anonymisation. Sans que le rapport la nomme, une colonne identifiante reste en clair sans que rien ne le dise
- Restaurer une sauvegarde ne lève plus `AttributeError` avant de lancer la commande : `_monitoring_restore` lisait `self._execute` là où `TODO` pose `self.execute`, et les deux entrées qui y mènent — la sauvegarde locale et la distante — étaient cassées. Un contrôle refuse le suivant : tout `self.X` que `TODO` LIT doit être posé par TODO ou par une de ses bases. Chercher le nom dans tout `script/todo/` ne voyait pas la faute, un autre objet du paquet posant bien `_execute` ; il faut le chercher dans les classes dont TODO HÉRITE
- Les scripts Selenium tournent sur un Python bâti sans `tkinter` — tout serveur dépourvu de paquet d'interface graphique. Ce module ne sert qu'au sélecteur de fichier du coffre, il est donc désormais optionnel : sans `tkinter` et sans chemin KDBX configuré, l'ouverture du coffre journalise une erreur et rend la main, au lieu de casser l'import de tous les scripts de pilotage de navigateur
- Le mode sombre repart en fenêtre privée sur un Firefox récent. La permission « Exécuter dans les fenêtres privées » est accordée à l'installation de l'extension, par le champ `allowPrivateBrowsing`, au lieu d'être cochée dans l'interface `about:addons` : Firefox refuse la navigation vers `about:addons` depuis le contexte contenu, et le contexte chrome exige `-remote-allow-system-access`, que geckodriver refuse via les capabilities, si bien que les deux voies vers cette case sont fermées. Un geckodriver qui ignore le champ installe sans la permission au lieu d'interrompre la session

<!-- [en] -->
## Removed
<!-- [fr] -->
## Retiré
<!-- [en] -->

- The `sshconf` dependency, declared and installed everywhere and imported nowhere

<!-- [fr] -->

- La dépendance `sshconf`, déclarée et installée partout et importée nulle part

<!-- [en] -->
## Security
<!-- [fr] -->
## Sécurité
<!-- [en] -->

- An API key and a bearer token are redacted too before a command is displayed, logged or reprinted: `OPENAI_API_KEY=` went out in the clear, and a header token escaped by construction, carrying neither an option name nor a variable name

<!-- [fr] -->

- Une clé d'API et un jeton Bearer sont caviardés eux aussi avant qu'une commande soit affichée, journalisée ou réimprimée : `OPENAI_API_KEY=` partait en clair, et un jeton d'en-tête échappait par construction, ne portant ni nom d'option ni nom de variable

<!-- [common] -->

## [1.8.0] - 2026-09-04

<!-- [en] -->
**Migration notes**

Recreating the virtual environment, the Python interpreter and the package
installer being chosen now. Use the installation guide from tool `make`.
Ubuntu 20.04 and 22.04 are no longer supported.

<!-- [fr] -->
**Notes de migration**

Recréer l'environnement virtuel, l'interpréteur Python et l'installateur de
paquets se choisissant désormais. Utiliser le guide d'installation depuis
l'outil `make`. Ubuntu 20.04 et 22.04 ne sont plus supportés.

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Deploy ERPLibre VMs with QEMU/KVM from cloud images: Ubuntu, Debian, Fedora, AlmaLinux, Rocky, openSUSE, Arch, Linux Mint, and Debian on s390x. Hardware, branch and Odoo version are set per machine
- Proxmox VE as a deployment target, its installation including the reboot it needs
- A QEMU menu: network status and repair, 3D acceleration, a diagnostic report, file recovery from a VM that no longer boots, virt-viewer and a remote desktop tunnel
- An install dashboard and Textual forms: deploy, follow, update, restart or delete a VM without leaving the screen
- A mobile development VM: PyCharm, Android Studio, an Android emulator and an adb tunnel
- A VPN tool, five free technologies from the menu, the secrets in a KeePassXC vault and a diagnosis that names the failing stage
- Automated Odoo migration: the tool drives the whole run, goes back to a step, and repairs what a version bump leaves behind
- Migration review: a verdict per step, smoke tests on every public URL, and a filestore check
- A read-only analysis toolkit for an Odoo database, a backup zip included, with PostgreSQL index advice
- Anonymising a production copy without AI, and duplicating a database neutralised for good
- Development assistants installed inside a VM, and a Git and Shell menu that installs what a checkout needs
- A writing convention for what stays in git, held by a `pre-commit` and a `commit-msg` hook
- `long_test/` — tests that create real machines, nested QEMU and Proxmox included, kept out of the unit runner
- NTFY, Forgejo, a local git server, e-mail from the CLI, and SSH configuration with recursive ProxyJump
- The Python interpreter and the package installer are chosen, through EL_PYTHON_PROVIDER and EL_PIP_PROVIDER
- The OCA generative AI policy, Claude Code agents and commands, and the context an assistant is given, shown from the menu
- Unit tests with a bilingual test plan, navigation telemetry for TODO, and Odoo 18 reading STL files

<!-- [fr] -->

- Déployer des VM ERPLibre en QEMU/KVM depuis des images cloud : Ubuntu, Debian, Fedora, AlmaLinux, Rocky, openSUSE, Arch, Linux Mint, et Debian sur s390x. Matériel, branche et version d'Odoo se règlent par machine
- Proxmox VE comme cible de déploiement, son installation comprenant le redémarrage qu'elle exige
- Un menu QEMU : état et réparation du réseau, accélération 3D, un rapport de diagnostic, récupération de fichiers sur une VM qui ne démarre plus, virt-viewer et un tunnel de bureau distant
- Un tableau de bord d'installation et des formulaires Textual : déployer, suivre, mettre à jour, redémarrer ou effacer une VM sans quitter l'écran
- Une VM de développement mobile : PyCharm, Android Studio, un émulateur Android et un tunnel adb
- Un outil VPN, cinq technologies libres au menu, les secrets dans un coffre KeePassXC et un diagnostic qui nomme l'étage fautif
- La migration Odoo automatisée : l'outil mène toute l'exécution, revient à une étape, et répare ce qu'un changement de version laisse derrière lui
- La revue de migration : un verdict par étape, des tests de fumée sur chaque URL publique, et un contrôle du filestore
- Une trousse d'analyse en lecture seule d'une base Odoo, archive de sauvegarde comprise, avec conseil d'index PostgreSQL
- L'anonymisation d'une copie de production sans IA, et la duplication d'une base neutralisée pour de bon
- Des assistants de développement posés dans une VM, et un menu Git et Shell qui installe ce qu'un checkout réclame
- Une convention d'écriture pour ce qui reste dans git, tenue par un hook `pre-commit` et un hook `commit-msg`
- `long_test/` — des tests qui créent de vraies machines, QEMU et Proxmox imbriqués compris, hors du lanceur unitaire
- NTFY, Forgejo, un serveur git local, le courriel depuis le CLI, et la configuration SSH avec ProxyJump récursif
- L'interpréteur Python et l'installateur de paquets se choisissent, par EL_PYTHON_PROVIDER et EL_PIP_PROVIDER
- La politique d'IA générative de l'OCA, les agents et commandes Claude Code, et le contexte donné à un assistant, montré depuis le menu
- Des tests unitaires avec un plan de test bilingue, la télémétrie de navigation de TODO, et Odoo 18 qui lit les fichiers STL

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- todo.py split into nine files, one per subject, with a shared base per form
- Every menu entry carries an icon, the menus are grouped into sections, and a countdown prompt gives 15 seconds to decide
- Branch, profile, type and timezone are chosen per VM rather than globally
- Installation covers Fedora, Debian, Ubuntu, Arch and openSUSE; repository sync and Poetry run in parallel, quiet unless EL_VERBOSE asks
- Node.js 22 for Capacitor 8, flanker for Odoo 18, CybroOdoo extras opt-in, and a Poetry dependency declinable per architecture
- A VM boots faster and picks the fastest reachable mirror, Canadian pacman mirrors coming first on Arch
- Staging names the files, never `git add -A`
- Enter targets the highest supported Odoo version, and a VM name drops the `latest` segment

<!-- [fr] -->

- todo.py éclaté en neuf fichiers, un par sujet, avec un socle commun par formulaire
- Chaque entrée de menu porte une icône, les menus sont regroupés en sections, et une invite à compte à rebours laisse 15 secondes pour décider
- La branche, le profil, le type et le fuseau se choisissent par VM plutôt que globalement
- L'installation couvre Fedora, Debian, Ubuntu, Arch et openSUSE ; la synchronisation des dépôts et Poetry tournent en parallèle, silencieux sauf si EL_VERBOSE le demande
- Node.js 22 pour Capacitor 8, flanker pour Odoo 18, les extras CybroOdoo optionnels, et une dépendance Poetry déclinable par architecture
- Une VM démarre plus vite et prend le miroir joignable le plus rapide, les miroirs pacman canadiens passant en tête sur Arch
- L'indexation nomme les fichiers, jamais `git add -A`
- Entrée cible la version d'Odoo la plus élevée supportée, et un nom de VM perd le segment `latest`

<!-- [en] -->
## Fixed
<!-- [fr] -->
## Corrigé
<!-- [en] -->

- The libvirt network no longer counts as its own collision, no longer leaves a host without network at the next boot, and its state is read in English whatever the locale
- QEMU deployment: sudo says why it needs a password, the `libvirt` group replaces it where it suffices, no host reboots unasked, and an orphan disk no longer blocks a creation
- Migration: the database drop, the account.root view Odoo 17 leaves behind, the pricelists a repair invented, and the assumptions the 13-to-18 run rested on
- Anonymisation respects what a value means, and no longer breaks past the 131 072-byte limit of a single argument
- Installation on Debian 13, Fedora, Ubuntu 26.04 and s390x: apt locks, missing compilers and headers, too little memory, and what a recent SWIG or PROJ needs
- Secrets: the KeePassXC vault opens on a server without tkinter, the forgejo installer stops echoing the password it set, and db_restore validates the master one
- A question is seen before it is answered, and one faulty repository no longer takes a whole batch down
- Three screens that fell over, a shrink that would have filled the disk, and a monitor that binned a VM before being sure
- The unit runner globs the whole directory, where it ran 1131 tests of 3703
- Proxmox no longer aims at the host instead of the VM

<!-- [fr] -->

- Le réseau libvirt ne compte plus comme sa propre collision, ne laisse plus un hôte sans réseau au démarrage suivant, et son état est lu en anglais quelle que soit la locale
- Le déploiement QEMU : sudo dit pourquoi il faut un mot de passe, le groupe `libvirt` le remplace là où il suffit, aucun hôte ne redémarre sans qu'on le demande, et un disque orphelin ne bloque plus
- La migration : l'effacement de base, la vue account.root que laisse Odoo 17, les listes de prix qu'une réparation inventait, et les suppositions sur lesquelles tenait le passage de 13 à 18
- L'anonymisation respecte ce qu'une valeur signifie, et ne casse plus au-delà de la limite de 131 072 octets d'un seul argument
- L'installation sur Debian 13, Fedora, Ubuntu 26.04 et s390x : verrous apt, compilateurs et en-têtes manquants, mémoire trop courte, et ce qu'exigent un SWIG ou un PROJ récents
- Les secrets : le coffre KeePassXC s'ouvre sur un serveur sans tkinter, l'installateur forgejo cesse de réafficher le mot de passe qu'il a posé, et db_restore valide celui du maître
- Une question se voit avant qu'on y réponde, et un dépôt fautif n'emporte plus tout un lot
- Trois écrans qui tombaient, une réduction qui aurait rempli le disque, et un suivi qui mettait une VM à la poubelle avant d'en être sûr
- Le lanceur unitaire balaie tout le répertoire, là où il exécutait 1131 tests sur 3703
- Proxmox ne vise plus l'hôte au lieu de la VM

<!-- [en] -->
## Removed
<!-- [fr] -->
## Retiré
<!-- [en] -->

- Ubuntu 20.04 and 22.04 support, on every architecture
- The residue check that called a language broken when its `active` is NULL

<!-- [fr] -->

- Le support d'Ubuntu 20.04 et 22.04, sur toutes les architectures
- Le contrôle de résidus qui jugeait cassée une langue dont `active` est NULL

<!-- [en] -->
## Security
<!-- [fr] -->
## Sécurité
<!-- [en] -->

- Passwords and tokens are redacted before a command is displayed, logged or reprinted
- The Odoo master password and the KeePass one leave the command line, an environment variable carrying them instead

<!-- [fr] -->

- Les mots de passe et jetons sont caviardés avant l'affichage, la journalisation ou le réaffichage d'une commande
- Le mot de passe maître d'Odoo et celui de KeePass quittent la ligne de commande, une variable d'environnement les portant à la place

<!-- [common] -->

## [1.7.0] - 2026-03-11

<!-- [en] -->
**Migration notes**

Recreating the virtual environment, use installation guide from tool `make`.

<!-- [fr] -->
**Notes de migration**

Recréer l'environnement virtuel, utiliser le guide d'installation depuis l'outil `make`.

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Odoo 12.0 to 18.0 in a single workspace, switched without reinstalling: the manifests, the configuration and the addons paths follow the version named in `.odoo-version`
- ERPLibre's Python separated from Odoo's — `.venv.erplibre` carries the repository's own tools, `.venv.odoo<version>` the server — so a tool of the repository no longer depends on the interpreter a given Odoo version imposes
- Auto-installation driven from TODO: the menu lays down the environment it needs, Poetry, the Google Repo manifests and the addons included, rather than printing a command to retype
- Migration of an Odoo database and its modules from TODO, `--neutralize` included, with the repair of the mail module that a move from PostgreSQL 17 to 18 leaves behind
- A hardening script for the installation
- The ERPLibre Home mobile application: TODO compiles it, deploys it, renames the software and changes its menu image
- The RobotLibre code generator, with the queue_job channels its configuration needs
- ERPLibre DevOps, and the automation procedure it describes
- The Selenium grid from `selenium_lib.py`: a KeePass vault opened for the run, file downloads, dark mode, video recording and a scenario library
- A performance script measuring the requests per second a website answers
- Deployment: Cloudflare DNS, nginx with a non-interactive certbot, Apache templates matching the nginx ones, and a systemd unit whose working directory is configurable
- The s390x mainframe architecture
- Addons OnlyOffice, Cetmix, OCA automation, OCA shopfloor, and the design-themes repository
- Database backup and erase commands, and a clearer restore naming
- A security check of the Python environment, from the menu
- TODO shows the documentation, downloads a database and helps with code formatting
- Killing an Odoo process by the port it holds, from the menu
- CLAUDE.md and the agent information document, so an assistant reads the repository's conventions instead of guessing them
- A FAQ entry on wkhtmltopdf for recent distributions

<!-- [fr] -->

- Odoo 12.0 à 18.0 dans un même espace de travail, changés sans réinstaller : les manifestes, la configuration et les chemins d'addons suivent la version nommée dans `.odoo-version`
- Le Python d'ERPLibre séparé de celui d'Odoo — `.venv.erplibre` porte les outils du dépôt, `.venv.odoo<version>` le serveur — si bien qu'un outil du dépôt ne dépend plus de l'interpréteur qu'impose une version d'Odoo
- L'auto-installation pilotée depuis TODO : le menu pose l'environnement dont il a besoin, Poetry, les manifestes Google Repo et les addons compris, au lieu d'afficher une commande à retaper
- La migration d'une base Odoo et de ses modules depuis TODO, `--neutralize` compris, avec la réparation du module mail que laisse un passage de PostgreSQL 17 à 18
- Un script de renforcement de la sécurité de l'installation
- L'application mobile ERPLibre Home : TODO la compile, la déploie, renomme le logiciel et change son image de menu
- Le générateur de code RobotLibre, avec les canaux queue_job que sa configuration réclame
- ERPLibre DevOps, et la procédure d'automatisation qu'il décrit
- La grille Selenium depuis `selenium_lib.py` : un coffre KeePass ouvert pour l'exécution, le téléchargement de fichiers, le mode sombre, l'enregistrement vidéo et une bibliothèque de scénarios
- Un script de performance qui mesure les requêtes par seconde qu'un site répond
- Le déploiement : DNS Cloudflare, nginx avec un certbot non interactif, gabarits Apache alignés sur ceux de nginx, et une unité systemd dont le répertoire de travail se configure
- L'architecture mainframe s390x
- Les addons OnlyOffice, Cetmix, OCA automation, OCA shopfloor, et le dépôt design-themes
- Des commandes de sauvegarde et d'effacement de base, et un nommage plus clair à la restauration
- Une vérification de sécurité de l'environnement Python, depuis le menu
- TODO affiche la documentation, télécharge une base et aide au formatage du code
- Tuer un processus Odoo par le port qu'il occupe, depuis le menu
- CLAUDE.md et le document d'information des agents, pour qu'un assistant lise les conventions du dépôt au lieu de les deviner
- Une entrée de FAQ sur wkhtmltopdf pour les distributions récentes

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- Odoo 18.0 becomes the default version of a checkout
- Docker moves to PostgreSQL 18, with the matching client
- The documentation is bilingual, generated by mmg from the `.base.md` sources: a `.md` or `.fr.md` edited directly is lost at the next generation
- The TODO menus are grouped into sections, and the English text serves as the i18n key rather than a code of its own
- The formatting script looks for the changed files in every repository, hidden addons included, and skips a repository that is not installed
- Odoo runs on a custom database, and the menu configures queue_job as well as the SSH forwarding a remote instance needs
- Killing a process by port asks before acting, through an interactive menu
- Neutralising a database goes through Odoo's own `--neutralize`
- LinuxMint 22.3, Ubuntu 25.10, and macOS without Python 3.7
- Odoo 18 dependencies: tldextract, PyYAML, pdfminer.six, and cryptography at its latest version
- A make target runs the unit tests
- The Makefile is split: its commands live in `conf/`, and `Common.Makefile` extends it for a project of one's own

<!-- [fr] -->

- Odoo 18.0 devient la version par défaut d'un checkout
- Docker passe à PostgreSQL 18, avec le client correspondant
- La documentation est bilingue, générée par mmg depuis les sources `.base.md` : un `.md` ou `.fr.md` modifié directement est perdu à la prochaine génération
- Les menus TODO sont regroupés en sections, et le texte anglais sert de clé i18n plutôt qu'un code à part
- Le script de formatage cherche les fichiers modifiés dans chaque dépôt, addons cachés compris, et saute un dépôt qui n'est pas installé
- Odoo tourne sur une base personnalisée, et le menu configure queue_job comme la redirection SSH qu'une instance distante réclame
- Tuer un processus par son port demande confirmation, par un menu interactif
- La neutralisation d'une base passe par le `--neutralize` d'Odoo
- LinuxMint 22.3, Ubuntu 25.10, et macOS sans Python 3.7
- Dépendances Odoo 18 : tldextract, PyYAML, pdfminer.six, et cryptography à sa dernière version
- Une cible make lance les tests unitaires
- Le Makefile est éclaté : ses commandes vivent dans `conf/`, et `Common.Makefile` l'étend pour un projet à soi

<!-- [en] -->
## Fixed
<!-- [fr] -->
## Corrigé
<!-- [en] -->

- The documentation accents, and the markdown generation running in parallel
- `git_tool` returns nothing instead of raising where `.git` is absent
- `poetry iscompatible` no longer crashes on a version carrying a letter, an alpha or a release candidate
- pymssql compiles again, and the Odoo 18 requirements leave pyssql out of a production install
- wkhtmltopdf is no longer offered where it does not exist: no package is published for s390x on Ubuntu 25.10
- Selenium: the snap Firefox path, a 60-second timeout when reaching for an element, execution in a private window, and a login that waits for Odoo 18
- The formatting script ignores the files and directories it must not touch
- `db_drop_all` runs its shell command, and the backup processing keeps the permissions of what it writes
- TODO: the first import, the regeneration of `.repo/local_manifests`, the database open dialog, and a missing Odoo version reported instead of a crash
- The code generator: creating a project, extracting a class carrying a selection, and reading a model through the Python 3.11 `ast` module rather than astor
- Docker: the duplicated Odoo 18 build target, and the compose file pinned to an image that works

<!-- [fr] -->

- Les accents de la documentation, et la génération markdown qui tourne en parallèle
- `git_tool` rend vide au lieu de lever là où `.git` est absent
- `poetry iscompatible` ne casse plus sur une version portant une lettre, une alpha ou une candidate
- pymssql se compile de nouveau, et les dépendances Odoo 18 laissent pyssql hors d'une installation de production
- wkhtmltopdf n'est plus proposé là où il n'existe pas : aucun paquet n'est publié pour s390x sur Ubuntu 25.10
- Selenium : le chemin du Firefox snap, un délai de 60 secondes pour atteindre un élément, l'exécution en fenêtre privée, et une connexion qui attend Odoo 18
- Le script de formatage ignore les fichiers et répertoires qu'il ne doit pas toucher
- `db_drop_all` exécute sa commande shell, et le traitement des sauvegardes garde les permissions de ce qu'il écrit
- TODO : le premier import, la régénération de `.repo/local_manifests`, le dialogue d'ouverture de base, et une version d'Odoo manquante signalée au lieu d'un plantage
- Le générateur de code : la création d'un projet, l'extraction d'une classe portant une sélection, et la lecture d'un modèle par le module `ast` de Python 3.11 plutôt que par astor
- Docker : la cible de compilation Odoo 18 en double, et le fichier compose épinglé sur une image qui fonctionne

<!-- [common] -->

## [1.6.0] - 2025-04-25

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Support multiple Odoo versions (12.0, 14.0, 16.0) in same workspace
    - This will help for the migration of modules
- Selenium script for increasing open software client interface and automating some actions.
    - Video recording
    - Support scrolling and word generating
- FAQ about kill git-daemon
- Supports Arch Linux, Ubuntu 23.10 to 25.04
- ADD repo JayVora-SerpentCS_SerpentCS_Contributions
- ADD repo CybroOdoo_CybroAddons

<!-- [fr] -->

- Support de plusieurs versions Odoo (12.0, 14.0, 16.0) dans le même espace de travail
    - Cela aidera pour la migration des modules
- Script Selenium pour augmenter l'interface client logiciel libre et automatiser certaines actions.
    - Enregistrement vidéo
    - Support du défilement et de la génération de mots
- FAQ sur comment tuer git-daemon
- Support d'Arch Linux, Ubuntu 23.10 à 25.04
- AJOUT du dépôt JayVora-SerpentCS_SerpentCS_Contributions
- AJOUT du dépôt CybroOdoo_CybroAddons

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- Refactor image_db regeneration, use configuration JSON to build image
- Guide for moving dev to prod
- Update Docker buster to bullseye
- Improve format script to help code-generator
- Improve PyCharm script
- Support OSX for open-terminal
- Remove docker-compose and replace by docker compose
- Update Poetry 1.3.1 to 1.5.1
- Test can be launched with a json configuration and support log/result individually
- Script to search docker compose into the system
- Script search class model can output into json format and support field information
- Improve Docker minimal installation docs in README for Ubuntu, test with
  Debian (https://github.com/ERPLibre/ERPLibre/issues/73)
- Statistic script showing evolution module into ERPLibre supporting Odoo 17 and Odoo 18
- Latest version wkhtmltopdf 0.12.6.1-3

<!-- [fr] -->

- Refactorisation de la régénération image_db, utilisation de la configuration JSON pour construire l'image
- Guide pour le passage de dev à prod
- Mise à jour Docker buster vers bullseye
- Amélioration du script de formatage pour aider le code-generator
- Amélioration du script PyCharm
- Support d'OSX pour open-terminal
- Suppression de docker-compose et remplacement par docker compose
- Mise à jour de Poetry 1.3.1 vers 1.5.1
- Les tests peuvent être lancés avec une configuration JSON et supportent les logs/résultats individuellement
- Script pour rechercher docker compose dans le système
- Le script de recherche de modèle de classe peut produire en format JSON et supporte les informations de champ
- Amélioration de la documentation d'installation Docker minimale dans le README pour Ubuntu, test avec
  Debian (https://github.com/ERPLibre/ERPLibre/issues/73)
- Script de statistiques montrant l'évolution des modules dans ERPLibre supportant Odoo 17 et Odoo 18
- Dernière version wkhtmltopdf 0.12.6.1-3

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- NPM installed locally and not globally
- Improve python code writer efficiency
- Config generator supporting space into ERPLibre directory
- Script to update Poetry to support @ URL
- OSX and recent Ubuntu installation
- Cloudflare script integration

<!-- [fr] -->

- NPM installé localement et non globalement
- Amélioration de l'efficacité du générateur de code Python
- Le générateur de configuration supporte les espaces dans le répertoire ERPLibre
- Script de mise à jour de Poetry pour supporter les URL avec @
- Installation OSX et Ubuntu récent
- Intégration du script Cloudflare

<!-- [common] -->

## [1.5.0] - 2023-07-07

<!-- [en] -->
**Migration notes**

Recreating the virtual environment

<!-- [fr] -->
**Notes de migration**

Recréer l'environnement virtuel

<!-- [common] -->

```bash
rm -rf ~/.poetry
rm -rf ~/.pyenv

rm ./get-poetry.py
rm -rf ./.venv

make install
```

<!-- [en] -->

Do a backup of your database and update all modules :

<!-- [fr] -->

Faire une sauvegarde de votre base de données et mettre à jour tous les modules :

<!-- [common] -->

```bash
./run.sh --no-http --stop-after-init -d DATABASE -u all
```

<!-- [en] -->
## Added
<!-- [fr] -->
## Ajouté
<!-- [en] -->

- Support Ubuntu 22.04 with installation script
- Module mail_history and fetchmail_thread_default in base image DB
- Makefile can generate image DB in parallel with `image_db_create_all_parallel`
- Makefile can run all code_generator with `run_parallel_cg` and `run_parallel_cg_template`
- Script to generate Pycharm configuration and exclude directory
- Support docker alpha+beta
- Limit memory execution when install in develop
- Template nginx configuration
- Script code count statistic
- Script show OCA evolution module statistic
- Windows development support, check documentation installation
- New project (code generator to create module) support params configuration
- Module sync_external_model to synchronise Odoo models with module

<!-- [fr] -->

- Support d'Ubuntu 22.04 avec script d'installation
- Module mail_history et fetchmail_thread_default dans l'image DB de base
- Le Makefile peut générer l'image DB en parallèle avec `image_db_create_all_parallel`
- Le Makefile peut exécuter tous les code_generator avec `run_parallel_cg` et `run_parallel_cg_template`
- Script pour générer la configuration PyCharm et exclure les répertoires
- Support docker alpha+beta
- Limitation de la mémoire d'exécution lors de l'installation en développement
- Template de configuration nginx
- Script de statistiques de comptage de code
- Script montrant l'évolution des modules OCA
- Support du développement Windows, consulter la documentation d'installation
- Nouveau projet (code generator pour créer un module) supporte la configuration par paramètres
- Module sync_external_model pour synchroniser les modèles Odoo avec un module

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- Odoo 12.0 update from 22-07-2020 to 01-01-2023
- Update pip dependency with security update
    - Pillow==9.3.0
    - psycopg2==2.9.5
    - Werkzeug==0.16.1
    - check diff of file pyproject.toml for all information
- Update to Python==3.7.16
- Update poetry==1.3.1
- Update multilingual-markdown==1.0.3
- Update imagedb with all Odoo update
- Repo documentation-user from Odoo change to documentation
- Repo odooaktiv/QuotationRevision is deleted
- Update all repo (91) to end of 2022
- Rename module project_task_subtask_time_range => project_time_budget
- Rename module project_task_time_range => project_time_range
- Refactor script emplacement, create directory in ./script/ per subject
- Use command parallel in Makefile
- Update sphinx version
- Improve script location

<!-- [fr] -->

- Mise à jour Odoo 12.0 du 22-07-2020 au 01-01-2023
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.3.0
    - psycopg2==2.9.5
    - Werkzeug==0.16.1
    - vérifier le diff du fichier pyproject.toml pour toutes les informations
- Mise à jour vers Python==3.7.16
- Mise à jour poetry==1.3.1
- Mise à jour multilingual-markdown==1.0.3
- Mise à jour imagedb avec toutes les mises à jour Odoo
- Le dépôt documentation-user d'Odoo change pour documentation
- Le dépôt odooaktiv/QuotationRevision est supprimé
- Mise à jour de tous les dépôts (91) à fin 2022
- Renommage du module project_task_subtask_time_range => project_time_budget
- Renommage du module project_task_time_range => project_time_range
- Refactorisation de l'emplacement des scripts, création de répertoires dans ./script/ par sujet
- Utilisation de la commande parallel dans le Makefile
- Mise à jour de la version sphinx
- Amélioration de l'emplacement des scripts

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Debian 11 installation script
- Test result
- OSX installation (not finish to support)
- Poetry update support '~='

<!-- [fr] -->

- Script d'installation Debian 11
- Résultats de tests
- Installation OSX (support non terminé)
- La mise à jour de Poetry supporte '~='

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

- Ubuntu 18.04 is broken, need to install manually nodejs and npm
- Module contract_portal and remove signature in portal contract, need an update
- Downgrade module helpdesk_mgmt to remove email team and tracking field
    - Module helpdesk_partner
    - Module helpdesk_service_call
    - Module helpdesk_supplier
    - Module helpdesk_mrp
    - Module helpdesk_mailing_list
    - Module helpdesk_join_team
- Module project_time_management
- Support of vatnumber, too old
- Deprecated python dependency like pycrypto

<!-- [fr] -->

- Ubuntu 18.04 est cassé, besoin d'installer manuellement nodejs et npm
- Module contract_portal et suppression de la signature dans le portail de contrat, nécessite une mise à jour
- Rétrogradation du module helpdesk_mgmt pour supprimer l'équipe email et le champ de suivi
    - Module helpdesk_partner
    - Module helpdesk_service_call
    - Module helpdesk_supplier
    - Module helpdesk_mrp
    - Module helpdesk_mailing_list
    - Module helpdesk_join_team
- Module project_time_management
- Support de vatnumber, trop ancien
- Dépendances Python dépréciées comme pycrypto

<!-- [common] -->

## [1.4.0] - 2022-10-05

<!-- [en] -->
**Migration note**

- Update module `website`,`website_form_builder`.
- For dev, run `poetry cache clear --all pypi`

<!-- [fr] -->
**Note de migration**

- Mettre à jour les modules `website`,`website_form_builder`.
- Pour le développement, exécuter `poetry cache clear --all pypi`

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Script run_parallel_test.sh to execute all tests in parallel for better execution speed
- Documentation to use docker in production
- Add repo:
    - Ajepe odoo-addons to support restful
    - OmniaGIT Odoo PLM
    - MathBenTech family-management
    - erplibre-3D-printing-addons
- Add module:
    - iohub_connector to support mqtt
    - website_snippet_all to install all snippets, extracted from all themes
    - website_blog_snippet_all to install website_snippet_all with website_blog and associated snippet
    - sinerkia_jitsi_meet to integrate Jitsi
    - erplibre_website_snippets_jitsi to integrate Jitsi in snippet, work in progress
- Add module by default:
    - auto_backup
    - muk_website_branding
    - website_snippet_anchor
    - website_anchor_smooth_scroll
    - crm_team_quebec
    - partner_no_vat
- Documentation Odoo dev
- Format command supported addons
- Install theme with Odoo command
- Script to install theme addons
- Image website with default theme
- Image erplibre demo
- Test with coverage

<!-- [fr] -->

- Script run_parallel_test.sh pour exécuter tous les tests en parallèle pour une meilleure vitesse d'exécution
- Documentation pour utiliser Docker en production
- Ajout de dépôts :
    - Ajepe odoo-addons pour supporter restful
    - OmniaGIT Odoo PLM
    - MathBenTech family-management
    - erplibre-3D-printing-addons
- Ajout de modules :
    - iohub_connector pour supporter mqtt
    - website_snippet_all pour installer tous les snippets, extraits de tous les thèmes
    - website_blog_snippet_all pour installer website_snippet_all avec website_blog et les snippets associés
    - sinerkia_jitsi_meet pour intégrer Jitsi
    - erplibre_website_snippets_jitsi pour intégrer Jitsi dans les snippets, travail en cours
- Ajout de modules par défaut :
    - auto_backup
    - muk_website_branding
    - website_snippet_anchor
    - website_anchor_smooth_scroll
    - crm_team_quebec
    - partner_no_vat
- Documentation Odoo dev
- Commande de formatage pour les addons supportés
- Installation de thème avec la commande Odoo
- Script pour installer les addons de thème
- Image du site web avec thème par défaut
- Image démo erplibre
- Tests avec couverture

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Downgrade sphinx to 1.6.7 to support Odoo dev documentation
- Update to poetry==1.1.14
- Update pip dependency with security update
    - Pillow==9.0.1
    - PyPDF2==1.27.8
    - lxml==4.9.1
- Code generator export website with attachments and scss design file with documentation
- Code generator support multiple snippets
- Into repo Numigi_odoo-project-addons rename module project_template to project_template_numigi
- Into repo Numigi_odoo-product-addons rename module product_dimension to product_dimension_numigi
- Into repo Numigi_odoo-partner-addons, re-enable auto-install module
- Into repo muk-it_muk_website, re-enable auto-install module

<!-- [fr] -->

- Rétrogradation de sphinx à 1.6.7 pour supporter la documentation Odoo dev
- Mise à jour vers poetry==1.1.14
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.0.1
    - PyPDF2==1.27.8
    - lxml==4.9.1
- Le code generator exporte le site web avec les pièces jointes et le fichier de design scss avec documentation
- Le code generator supporte les snippets multiples
- Dans le dépôt Numigi_odoo-project-addons, renommage du module project_template en project_template_numigi
- Dans le dépôt Numigi_odoo-product-addons, renommage du module product_dimension en product_dimension_numigi
- Dans le dépôt Numigi_odoo-partner-addons, réactivation du module auto-install
- Dans le dépôt muk-it_muk_website, réactivation du module auto-install

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Poetry supports insensitive python dependency
- Code generator new project supports relative path and check duplicated paths
- Muk web theme table header background-color and on hover for Many2many
- Script docker-compose use lowercase name
- website_form_builder HTML support and allow option to align send button
- Odoo cherry-pick 2 commits bus fix
- Minor fix css color into module hr_theme from repo CybroOdoo_OpenHRMS
- Typo in project task when logging time

<!-- [fr] -->

- Poetry supporte les dépendances Python insensibles à la casse
- Le nouveau projet du code generator supporte les chemins relatifs et vérifie les chemins dupliqués
- Couleur d'arrière-plan de l'en-tête de tableau du thème web Muk et survol pour Many2many
- Le script docker-compose utilise des noms en minuscules
- website_form_builder support HTML et option pour aligner le bouton d'envoi
- Cherry-pick Odoo de 2 commits correctif bus
- Correction mineure de couleur CSS dans le module hr_theme du dépôt CybroOdoo_OpenHRMS
- Faute de frappe dans la tâche de projet lors de la saisie du temps

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

- Module package erplibre from ERPLibre_erplibre_addons and use instead image creation, check Makefile

<!-- [fr] -->

- Paquet de module erplibre de ERPLibre_erplibre_addons, utiliser à la place la création d'image, voir le Makefile

<!-- [common] -->

## [1.3.0] - 2022-01-25

<!-- [en] -->
**Migration note**

With new version of poetry, a bug occurs in the update. The solution is to delete the directory to let it
recreate. `rm -rf ~/.poetry`

<!-- [fr] -->
**Note de migration**

Avec la nouvelle version de poetry, un bogue survient lors de la mise à jour. La solution est de supprimer le répertoire pour le laisser
se recréer. `rm -rf ~/.poetry`

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Code generator supports view : activity, calendar, diagram, form, graph, kanban, pivot, search, timeline and tree
- Code generator supports portal view field and form creation
- Code generator generates generic snippets for demo_portal
- Code generator generates code_generator with code_generator_code_generator
- Code generator tests mariadb migrator
- Code generator supports javascript interpretation for snippet
- Code generator supports inheritance
- Code generator new project to create the suite of generation code
- Script to test the generation of module `code_generator`
- Make test_full_fast to run all test in parallel
- Module `web_timeline` and `web_diagram_position` in base image.
- Module `odoo-formio` from novacode-nl
- Module `design_themes` from Odoo
- Format python header with isort

<!-- [fr] -->

- Le code generator supporte les vues : activity, calendar, diagram, form, graph, kanban, pivot, search, timeline et tree
- Le code generator supporte la création de champs de vue portail et de formulaires
- Le code generator génère des snippets génériques pour demo_portal
- Le code generator génère code_generator avec code_generator_code_generator
- Le code generator teste le migrateur mariadb
- Le code generator supporte l'interprétation javascript pour les snippets
- Le code generator supporte l'héritage
- Nouveau projet du code generator pour créer la suite de génération de code
- Script pour tester la génération du module `code_generator`
- Make test_full_fast pour exécuter tous les tests en parallèle
- Module `web_timeline` et `web_diagram_position` dans l'image de base.
- Module `odoo-formio` de novacode-nl
- Module `design_themes` d'Odoo
- Formatage de l'en-tête Python avec isort

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update to Python==3.7.12
- Update to poetry==1.1.12
- Update pip dependency with security update
    - Pillow==9.0.0
    - lxml==4.7.1
    - babel==2.9.1
    - pyyaml==6.0
    - reportlab==3.6.5
- Web diagram module has all color of the rainbow in option
- Refactor and simplify code of code_generator, better support of code reader

<!-- [fr] -->

- Mise à jour vers Python==3.7.12
- Mise à jour vers poetry==1.1.12
- Mise à jour des dépendances pip avec correctif de sécurité
    - Pillow==9.0.0
    - lxml==4.7.1
    - babel==2.9.1
    - pyyaml==6.0
    - reportlab==3.6.5
- Le module web diagram a toutes les couleurs de l'arc-en-ciel en option
- Refactorisation et simplification du code du code_generator, meilleur support du lecteur de code

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Downgrade Werkzeug==0.11.15, only this version is supported by Odoo 12.0. This fixes some http request behind a proxy.

<!-- [fr] -->

- Rétrogradation Werkzeug==0.11.15, seule cette version est supportée par Odoo 12.0. Cela corrige certaines requêtes HTTP derrière un proxy.

<!-- [common] -->

## [1.2.1] - 2021-09-28

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- doc/migration.md

<!-- [fr] -->

- doc/migration.md

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update pip dependency with security update
    - Jinja2==2.11.3
    - lxml==4.6.3
    - cryptography==3.4.8
    - psutil==5.6.6
    - Pillow==8.3.2
    - Werkzeug==0.15.3
- Script separate generate_config.sh from install_locally.sh
- Improve developer documentation
- More Docker script

<!-- [fr] -->

- Mise à jour des dépendances pip avec correctif de sécurité
    - Jinja2==2.11.3
    - lxml==4.6.3
    - cryptography==3.4.8
    - psutil==5.6.6
    - Pillow==8.3.2
    - Werkzeug==0.15.3
- Séparation du script generate_config.sh de install_locally.sh
- Amélioration de la documentation développeur
- Plus de scripts Docker

<!-- [en] -->
#### Code generator
<!-- [fr] -->
#### Code generator
<!-- [en] -->

- Improve db_servers generation code
- Improve wizard generate UI menu

<!-- [fr] -->

- Amélioration du code de génération db_servers
- Amélioration du menu UI de l'assistant de génération

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Mobile view menu item in Web interface from muk_web_theme

<!-- [fr] -->

- Élément de menu vue mobile dans l'interface Web de muk_web_theme

<!-- [common] -->

## [1.2.0] - 2021-07-21

<!-- [en] -->
**Migration note**

Because addons repository has change, config file need to be updated.

- When upgrading to version 1.2.0:
    - From docker
        - Clone project if only download docker-compose
<!-- [fr] -->
**Note de migration**

Parce que le dépôt d'addons a changé, le fichier de configuration doit être mis à jour.

- Lors de la mise à niveau vers la version 1.2.0 :
    - Depuis docker
        - Cloner le projet si vous avez seulement téléchargé docker-compose
<!-- [common] -->
            - `git init`
            - `git remote add origin https://github.com/erplibre/erplibre`
            - `git fetch`
            - `mv ./docker-compose.yml /tmp/temp_docker-compose.yml`
            - `git checkout master`
            - `mv /tmp/temp_docker-compose.yml ./docker-compose.yml`
<!-- [en] -->
        - Update `./docker-compose.yml` depending of difference with git.
        - Run script `make docker_exec_erplibre_gen_config`
        - Restart the docker `make docker_restart_daemon`
    - From vanilla
        - Run script `make install_dev`
        - Restart your daemon
        - Regenerate master password manually

<!-- [fr] -->
        - Mettre à jour `./docker-compose.yml` selon les différences avec git.
        - Exécuter le script `make docker_exec_erplibre_gen_config`
        - Redémarrer le docker `make docker_restart_daemon`
    - Depuis une installation vanilla
        - Exécuter le script `make install_dev`
        - Redémarrer votre daemon
        - Régénérer le mot de passe maître manuellement

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Adapt script to give an execution status
- Multilingual markdown
- Guide to use Cloudflare with DDNS
- Script to check git diff and ignore date
- Repo with ERPLibre image
- Improve git repo usage, filter repo by use case
- ERPLibre theme website of TechnoLibre
- ERPLibre website snippet
    - Basic HTML snippets
    - Snippet card
    - Snippet timelines
- Module contract_digitized_signature with contract_portal
- Module disable auto_backup
- Odoo cli db command to manipulate restoration db
- Odoo cli i18n command to generate i18n pot files

<!-- [fr] -->

- Adaptation du script pour donner un statut d'exécution
- Markdown multilingue
- Guide pour utiliser Cloudflare avec DDNS
- Script pour vérifier le diff git et ignorer la date
- Dépôt avec l'image ERPLibre
- Amélioration de l'utilisation du dépôt git, filtrer les dépôts par cas d'utilisation
- Thème de site web ERPLibre de TechnoLibre
- Snippet de site web ERPLibre
    - Snippets HTML de base
    - Snippet carte
    - Snippets chronologie
- Module contract_digitized_signature avec contract_portal
- Module disable auto_backup
- Commande CLI Odoo db pour manipuler la restauration de base de données
- Commande CLI Odoo i18n pour générer les fichiers pot i18n

<!-- [en] -->
#### Makefile
<!-- [fr] -->
#### Makefile
<!-- [en] -->

- Format code
- Code generator test
- Addons installation
- OS installation
- Restore database
- Docker execution

<!-- [fr] -->

- Formatage du code
- Test du code generator
- Installation des addons
- Installation du système d'exploitation
- Restauration de base de données
- Exécution Docker

<!-- [en] -->
#### Code generator
<!-- [fr] -->
#### Code generator
<!-- [en] -->

- Code generator for Odoo module, depending of ERPLibre
- Support map geospatial
- Support i18n
- Script to transform Python and XML to Python code writer script to regenerate themselves

<!-- [fr] -->

- Code generator pour les modules Odoo, dépendant d'ERPLibre
- Support des cartes géospatiales
- Support i18n
- Script pour transformer Python et XML en script d'écriture de code Python pour se régénérer eux-mêmes

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update Python dependency with Poetry
- Format all Python code with black
- Module auto_backup with sftp host key
- Module muk_website_branding use ERPLibre branding
- Update docs with vscode support, custom document layout, custom email template and trick to use params to share
  variable

<!-- [fr] -->

- Mise à jour des dépendances Python avec Poetry
- Formatage de tout le code Python avec black
- Module auto_backup avec clé d'hôte sftp
- Le module muk_website_branding utilise le branding ERPLibre
- Mise à jour de la documentation avec le support vscode, mise en page de document personnalisée, modèle d'email personnalisé et astuce pour utiliser les paramètres de partage
  de variables

<!-- [en] -->
#### Docker
<!-- [fr] -->
#### Docker
<!-- [en] -->

- Use buster python 3.7.7 image to remove pyenv
- Update Postgresql to support Postgis
- Support volume addons /ERPLibre/addons/addons

<!-- [fr] -->

- Utilisation de l'image buster python 3.7.7 pour supprimer pyenv
- Mise à jour de PostgreSQL pour supporter PostGIS
- Support du volume addons /ERPLibre/addons/addons

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Ubuntu installation
- Poetry installation
- Geospatial with postgis can be installed

<!-- [fr] -->

- Installation Ubuntu
- Installation de Poetry
- Le géospatial avec PostGIS peut être installé

<!-- [common] -->

## [1.1.1] - 2020-12-11

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Developer, test, migration and user documentation
- Branding ERPLibre with muk_branding
- Uninstall module from parameter Odoo
- Makefile to generate ERPLibre documentation WIP
- Docker support volume on /etc/odoo
- Docker support update database

<!-- [fr] -->

- Documentation développeur, test, migration et utilisateur
- Branding ERPLibre avec muk_branding
- Désinstallation de module depuis les paramètres Odoo
- Makefile pour générer la documentation ERPLibre (travail en cours)
- Support Docker du volume sur /etc/odoo
- Support Docker de la mise à jour de base de données

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Better documentation on how to use ERPLibre and release
- Support wkhtmltox_0.12.6-1

<!-- [fr] -->

- Meilleure documentation sur l'utilisation d'ERPLibre et les versions
- Support de wkhtmltox_0.12.6-1

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- db_backup to accept public host key on sftp
- Docker dependency
- Freeze poetry version 1.0.10

<!-- [fr] -->

- db_backup pour accepter la clé d'hôte publique sur sftp
- Dépendances Docker
- Gel de la version poetry 1.0.10

<!-- [common] -->

## [1.1.0] - 2020-09-30

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Docker
- Pyenv to manage python version
- Poetry to manage python dependencies
    - Script poetry_update to search all dependencies in addons
- Travis CI WIP
- TODO.md
- Guide to update all repositories with community
- Update manifest
    - Add missing OCA repos
    - Add medical, property management and more
    - Add cloud/saas repo

<!-- [fr] -->

- Docker
- Pyenv pour gérer les versions Python
- Poetry pour gérer les dépendances Python
    - Script poetry_update pour rechercher toutes les dépendances dans les addons
- Travis CI (travail en cours)
- TODO.md
- Guide pour mettre à jour tous les dépôts avec la communauté
- Mise à jour du manifeste
    - Ajout des dépôts OCA manquants
    - Ajout de médical, gestion immobilière et plus
    - Ajout du dépôt cloud/saas

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Update to Odoo Community 12.0 and all addons
- Rename venv to .venv
- More documentation on how to use ERPLibre

<!-- [fr] -->

- Mise à jour vers Odoo Community 12.0 et tous les addons
- Renommage de venv en .venv
- Plus de documentation sur l'utilisation d'ERPLibre

<!-- [common] -->

## [1.0.1] - 2020-07-14

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Improved documentation with development and production environment
- Improved documentation with git repo
- Move default.xml manifest to root, the default location
- Support default.staged.xml to update prod with dev
- Feature to show diff between manifests or between repo of different manifests
- Update manifest
    - Muk theme in erplibre_base
    - Add draft account invoice approbation in portal
    - New module sale_fix_update_price_unit_when_update_qty
    - New module account_invoice_approbation
    - New module sale_margin_editor

<!-- [fr] -->

- Amélioration de la documentation avec l'environnement de développement et de production
- Amélioration de la documentation avec le dépôt git
- Déplacement du manifeste default.xml à la racine, l'emplacement par défaut
- Support de default.staged.xml pour mettre à jour la prod avec le dev
- Fonctionnalité pour afficher le diff entre les manifestes ou entre les dépôts de différents manifestes
- Mise à jour du manifeste
    - Thème Muk dans erplibre_base
    - Ajout du brouillon d'approbation de facture dans le portail
    - Nouveau module sale_fix_update_price_unit_when_update_qty
    - Nouveau module account_invoice_approbation
    - Nouveau module sale_margin_editor

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Production installation with git_repo

<!-- [fr] -->

- Installation de production avec git_repo

<!-- [common] -->

## [1.0.0] - 2020-07-04

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Environment of development, discovery and production with documentation and script.
- Google git-repo to support addons repository instead of using Git submodule.

<!-- [fr] -->

- Environnement de développement, découverte et production avec documentation et scripts.
- Google git-repo pour supporter le dépôt d'addons au lieu d'utiliser les sous-modules Git.

<!-- [en] -->
### Removed
<!-- [fr] -->
### Supprimé
<!-- [en] -->

- Git submodule

<!-- [fr] -->

- Sous-modules Git

<!-- [common] -->

## [0.1.1] - 2020-04-28

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Support helpdesk supplier, helper, employee and services
- Support [SanteLibre.ca](https://santelibre.ca) with MRP, website, hr, ecommerce
- Donation module with thermometer for website
- Script to fork project and all repos in submodule to create ERPLibre

<!-- [fr] -->

- Support du helpdesk fournisseur, assistant, employé et services
- Support de [SanteLibre.ca](https://santelibre.ca) avec MRP, site web, RH, commerce en ligne
- Module de don avec thermomètre pour le site web
- Script pour forker le projet et tous les dépôts en sous-module pour créer ERPLibre

<!-- [common] -->

## [0.1.0] - 2020-04-20

<!-- [en] -->
### Added
<!-- [fr] -->
### Ajouté
<!-- [en] -->

- Move project from https://github.com/mathbentech/InstallScript to ERPLibre.
- Support of Odoo Community 12.0 2019-11-19 94bcbc92e5e5a6fd3de7267e3c01f8c11fb045f4.

<!-- [fr] -->

- Déplacement du projet de https://github.com/mathbentech/InstallScript vers ERPLibre.
- Support d'Odoo Community 12.0 2019-11-19 94bcbc92e5e5a6fd3de7267e3c01f8c11fb045f4.

<!-- [en] -->
### Changed
<!-- [fr] -->
### Modifié
<!-- [en] -->

- Support scrummer, project, sale, website, helpdesk and hr
- Support Nginx and improve installation

<!-- [fr] -->

- Support de scrummer, projet, vente, site web, helpdesk et RH
- Support de Nginx et amélioration de l'installation

<!-- [en] -->
### Fixed
<!-- [fr] -->
### Corrigé
<!-- [en] -->

- Support only python3.6 and python3.7, python3.8 causes error in runtime.

<!-- [fr] -->

- Support uniquement de python3.6 et python3.7, python3.8 cause des erreurs à l'exécution.

<!-- [common] -->

[Unreleased]: https://github.com/ERPLibre/ERPLibre/compare/v1.8.0...HEAD

[1.8.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.7.0...v1.8.0

[1.7.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.6.0...v1.7.0

[1.6.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.5.0...v1.6.0

[1.5.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.4.0...v1.5.0

[1.4.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.3.0...v1.4.0

[1.3.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.2.1...v1.3.0

[1.2.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.2.0...v1.2.1

[1.2.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.1.1...v1.2.0

[1.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...v1.1.1

[1.1.0]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.1...v1.1.0

[1.0.1]: https://github.com/ERPLibre/ERPLibre/compare/v1.0.0...v1.0.1

[1.0.0]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.1...v1.0.0

[0.1.1]: https://github.com/ERPLibre/ERPLibre/compare/v0.1.0...v0.1.1

[0.1.0]: https://github.com/ERPLibre/ERPLibre/releases/tag/v0.1.0
