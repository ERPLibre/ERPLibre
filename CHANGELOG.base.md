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
- A download cache shared by the QEMU VMs of a host, installed from **Deployment › QEMU cache**. Two VMs of the same distribution stop pulling the same hundreds of megabytes twice: a package file is served from disk, while an index is always taken from upstream, so a withdrawn package can never turn into a « failed retrieving file … 404 ». An index is stored all the same and only comes back out when upstream is unreachable, which is what makes an offline deployment possible. The cache never shrinks by itself: `--status` says what it occupies
- Interception is transparent and covers the whole host bridge, so a VM cannot opt out from the inside. Every VM trusts the cache's authority as long as the service runs. To take ONE machine out, tick « keep this VM out of the download cache » when deploying: its MAC address is fixed before creation and an exception is posted on the host. To take them all out, stop the service — its rules leave with it. A Proxmox host that is itself a VM here is no exception: the machines it carries come out behind its address, so the deployment poses the authority in each of them, by ssh, before installing anything
- The measurement is not limited to Arch: any catalogue system whose package family is known, and either a batch of packages or the real install of ERPLibre and Odoo 18. Measured on Ubuntu 24.04 with that real install, the second VM pulled **zero byte** of package from the network and finished 19 % faster. Verified on the seven systems of the catalogue
- Git is MIRRORED rather than cached: its protocol is a negotiation, the server computing its answer from what the client already holds, so no answer is reusable. A bare mirror per upstream repository is kept on the host and served locally, and a mirror already held serves with no network at all — measured, a repository cloned inside a VM while the cache's upstream was cut. Measured on a full ERPLibre install: the second VM pulled **zero** git request from upstream, where git had been four fifths of the traffic. **Deployment › QEMU cache › Git mirrors** fills them ahead from the manifests, so the first VM does not pay every clone
- An offline deployment also covers the base suite of a cloud image. Its apt REVALIDATES the index it ships instead of downloading it, upstream answers 304, and the cache had no body to keep — so that one suite, and only it, was missing offline while its `-updates` and `-security` neighbours came off the disk. A conditional request for something the cache does not hold now goes upstream without its condition, once, and a client that holds its own copy gets 304 rather than 504 when upstream is mute.
- What an offline deployment covers, exactly: packages, repository indexes and git. NOT what the cache is forbidden to decrypt — a client carrying its own trust store, npm and poetry among them, is tunnelled opaquely, and a tunnel carries nothing once the network is gone. A full ERPLibre install therefore still needs the network, though everything the cache holds is served from disk
- A mirror is COMPLETE where `repo sync` clones at depth one, so it costs tens of gigabytes. Below ten gigabytes free, no new mirror is created and the request goes back upstream. The diagnosis says what the objects and the mirrors each occupy
- **Deployment › QEMU cache › Age and cleanup** groups the cache by age of last use (day, week or month; objects and git repositories apart) and gives back what has not served for a chosen delay, or everything. A served object has its date renewed, so « old » means « no longer used ». Both cleanups say what would go before erasing anything, and entry 5 lists the mirrors heaviest first to remove one
- `long_test/qemu_cache.py` measures whether the cache really serves the second VM, and `--hors-ligne` cuts the upstream of the cache service alone to prove a third VM still builds from the stored index
- Before cutting, the form says whether the cache holds the base suite of each system asked for: F5 warns « cache holds nothing for ubuntu 26.04 » and a second F5 goes ahead anyway. The verdict is given only where a release is named unambiguously in the URL — the apt families — rather than reassuring wrongly elsewhere. The verdict is given component by component — `main`, `universe`, `restricted`, `multiverse`, on the base suite and on its `-updates` and `-security` companions — because a single stored URL used to silence it while a whole component was missing, and apt only said so twenty minutes later, by « Unable to locate package »
- **Deployment › QEMU cache › Copy it to another machine** carries the store to another ERPLibre host in a single stream — `tar`, compressed, over ssh, no intermediate file for tens of gigabytes — and hands the files to the service account on arrival, the same account rarely bearing the same number on two machines. Only the STORE travels: an object is keyed by its URL and never by the machine that fetched it, and a git mirror is a repository. The settings stay behind — bridge, subnet and authority belong to the host, and entry 1 poses them there
- The deployment form carries a **Network** section with « No internet connection »: for the whole deployment, install included, the cache service loses its way out AND the VMs lose theirs — ping, other ports, UDP, IPv6 — so a step that takes any path but the cache fails instead of quietly succeeding online. Names no longer resolve through the internet either: the host answers every name itself with an address the cache intercepts, so only what the cache holds can be reached; dnsmasq must be installed on the host. A VM behind the cache pulls from one fixed apt mirror: cloud-init's mirror search discards every mirror behind a resolver that answers every name, and would fall back on another mirror than the one the previous VMs filled the cache from. The cut refuses rather than drops, so an address the cache does not hold answers 504 at once instead of after a connection timeout; a kernel that cannot load the reject module gets the dropping set instead. Offered only where the cache runs, and the deployment refuses rather than run with the upstream still up, a VM built that way succeeding for the wrong reason. **Proxmox VE** carries the same box, offered where its host is itself a VM of this bridge: its guests come out behind its address, so the local cut covers them and nothing is posted on the remote host. A Proxmox host that does not live here is never offered it — nothing here can cut its way out
- A Proxmox VE deployment can ask for **3D acceleration**. The VM is created with an accelerated screen (`--vga virtio-gl`) rather than the serial console as its display, and the account joins the GPU groups INSIDE the guest: the render node belongs to `root:render`, so without them every GL application falls back to software rendering while the VIRGL negotiation reports success, and nothing says so. The box is offered only where the remote host has a render node AND the three libraries Proxmox loads for that screen — VIRGL, GL and EGL. It names the missing ones and refuses to start the machine, once its disk is written and its configuration posted, so a host carrying GL without EGL would fail at the very last step. Where a piece is missing the form says which, and the package to install on the host: a box that vanishes without a word reads as a regression. A button installs them without leaving the screen — the form hands the terminal back so sudo can ask for a password and apt can be watched — then reads the host again rather than taking apt's word for it, and the box appears in place of the message. The serial port stays posted, so `qm terminal` keeps working
- Offline, the cache replays what an online pass saw, not only 200 bodies: redirects, definitive refusals (404/410) and HEAD answers of volatile URLs are kept without a body, under keys of their own, and served ONLY when upstream is mute. A TUF client probing the next version of its root gets the 404 it expects instead of a 504, so mise installs Python offline with its Sigstore verification intact; GNOME extensions, Claude Code's installer and rtk's version lookup follow their redirects offline
- The offline cut ends when the last installation ends, not when the monitor closes: a root unit, handed the lift at launch, waits for every installation's exit marker and survives the monitor closed early, todo.py killed or the terminal gone — 12 h at most. The monitor is therefore required while offline. A second offline deployment is refused while one runs, and an online deployment started meanwhile is told it would run offline
- F5 also reads the previous offline runs of the same VM and warns « at least N addresses were missing », minus what the store holds now (`erplibre_go_qemu_cache --detient`, read-only, no root). **Deployment › QEMU cache › Fill what offline runs lacked** replays them online, through the cache
- The install log names the commit the VM runs; offline, the recap says, branch by branch, which commit the cache's mirror will give
- `long_test/qemu_cache.py --distro tous` (or a comma list) chains one campaign per catalogue system, destroys each system's VMs before the next, and ends on a table of verdict, durations and upstream bytes. A failure does not stop the series
- The QEMU download cache can clean itself up every day: by age (`EL_PURGE_AGE`, e.g. `90j`) and by size ceiling (`EL_MAX_SIZE`, e.g. `50G`, the least recently served going first, objects and git mirrors alike). Both are off by default and set from **Deployment › QEMU cache › Automatic cleanup**, which previews what would go; `--purge-to-size` runs the ceiling by hand. A reinstall keeps the values chosen
- NixOS 25.11 as a deployable system, alongside the eight others. It is the only one no distribution publishes a cloud image for: the image is rebuilt by a third party, so its release is pinned, its sha256 verified at every download, and its origin printed before anything is created. cloud-init receives no network configuration there — its networkd renderer takes the key of a block as an interface NAME, where netplan honours a `match:` — and the account is created with `/bin/sh`, sshd refusing an account whose shell does not exist
- ERPLibre installed on NixOS, its dependencies DECLARED in `conf/nixos/erplibre.nix` and applied by `nixos-rebuild`, where the four other families install them one command at a time. `services.envfs` answers `/usr/bin/env` and `programs.nix-ld` gives manylinux wheels the dynamic loader they ask for; the headers of what has no wheel are linked into the system profile, and its libraries reach the loader too, a module compiled on the machine carrying no RPATH. The install reaches it from the menu like any other distribution: the bootstrap poses git, make and python3 — absent from that image — in the user profile for the clone, and « make install_os » redeclares them for the system. Checked on a VM: the 362-package lock installs and Odoo answers over HTTP
- A `nix + nixos-anywhere` option on the OTHER distributions, the reverse of picking NixOS: it leaves an ordinary VM able to install NixOS onto any machine reachable over SSH. Nix is called by absolute path, the remote shell's PATH being frozen before the installer drops the binary, and the flake features are repeated on the command line, writing `nix.conf` needing a sudo that may fail
- NixOS deploys on a **Proxmox** host as it does on QEMU/KVM, which took three fixes no code reading could have found. Its image has no BIOS boot sector: a VM created in SeaBIOS reports « running » with a silent console, so the catalogue now marks which images need UEFI — one marker per distribution, since Debian 13 boots in SeaBIOS on that same host. `--ciuser` and `--sshkeys` defer to the image's DEFAULT account, which NixOS declares as another name: the repository's own cloud-config now travels as a snippet for every distribution, carrying an explicit `users:` block. And the cloud-init drive moves to the SCSI bus — an image built for virtio alone has no ATA driver and never sees an IDE drive, so cloud-init hunted network datasources and the VM came up with no account at all. Checked end to end: NixOS answers with `/bin/sh`, Debian 13 with `/bin/bash`, sudo on both
- The third-party image is verified against the sum the repository pins for it on the Proxmox path too, where a bare `wget` used to be enough. One accessor carries that sum for both paths, and the check runs even on a cached image — the case aimed at is a file substituted or truncated between deployments, which a presence test cannot see
- One entry of the download cache can be removed, by URL. A checksum that does not match invalidated nothing: the store kept serving the same bytes, and re-downloading changed nothing since the store is what answers. Neither existing purge reaches it — `--purge` erases everything, and `--purge-older-than` skips what is recent while every service resets that date, so a poisoned object that keeps being served never ages. `--oublie` is symmetric to `--detient`: same input lines, same key functions, same refusals, and a present object that resists is reported as a refusal rather than a forget. Both checksum failures now name it, with the exact URL
- The install log carries what the host decided before launching: the download cache authority placed or refused, the bypass, the mirror. Those lines were said on a console that scrolls away, while the file reopened after a failure held only the symptom — on a guest with no trust store, a refused certificate, hundreds of derivations to build and six hundred lines of errors, without a word on the cause
- One entry of the download cache can be forgotten from the menu, under « Age and cleanup ». The binary could already do it; the menu offered only the two bulk purges, neither of which reaches a single object — « erase what has not served » never reaches one the service rejuvenates each time it serves it, and « erase everything » costs the whole cache for one file. `--detient` runs first and is the preview: same line, same key, nothing modified

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
- Un cache de téléchargement partagé par les VM QEMU d'un hôte, installé depuis **Déploiement › Cache QEMU**. Deux VM de la même distribution cessent de tirer deux fois les mêmes centaines de mégaoctets : un fichier de paquet est servi du disque, tandis qu'un index est toujours repris à l'amont, si bien qu'un paquet retiré ne peut jamais devenir un « failed retrieving file … 404 ». L'index est stocké quand même et ne ressort que si l'amont est injoignable, ce qui rend un déploiement hors ligne possible. Le cache ne diminue jamais de lui-même : `--status` dit ce qu'il occupe
- L'interception est transparente et vaut pour tout le pont de l'hôte : une VM ne peut pas s'y soustraire de l'intérieur. Toutes approuvent l'autorité du cache tant que le service tourne. Pour en soustraire UNE, cocher « soustraire cette VM au cache » au déploiement : son adresse MAC est fixée avant la création et une exception est posée sur l'hôte. Pour les soustraire toutes, arrêter le service — ses règles partent avec lui. Un hôte Proxmox qui est lui-même une VM d'ici n'y échappe pas : les machines qu'il porte sortent derrière son adresse, et le déploiement pose donc l'autorité dans chacune, par ssh, avant d'installer quoi que ce soit
- La mesure ne se limite plus à Arch : tout système du catalogue dont la famille de paquets est connue, et au choix un lot de paquets ou l'installation réelle d'ERPLibre et d'Odoo 18. Mesuré sur Ubuntu 24.04 avec cette installation réelle, la seconde VM n'a tiré **aucun octet** de paquet du réseau et a fini 19 % plus vite. Vérifié sur les sept systèmes du catalogue
- Git est mis en MIROIR plutôt que caché : son protocole est une négociation, le serveur calculant sa réponse d'après ce que le client détient déjà, si bien qu'aucune réponse ne se réutilise. Un miroir nu par dépôt amont est tenu sur l'hôte et servi localement, et un miroir déjà détenu sert sans aucun réseau — mesuré, un dépôt cloné dans une VM alors que l'amont du cache était coupé. Mesuré sur une installation complète d'ERPLibre : la seconde VM n'a tiré **aucune** requête git de l'amont, là où git pesait quatre cinquièmes du trafic. **Déploiement › Cache QEMU › Miroirs git** les remplit d'avance depuis les manifestes, pour que la première VM ne paie pas tous les clonages
- Un déploiement hors ligne couvre aussi la suite de base d'une image cloud. Son apt REVALIDE l'index qu'elle livre au lieu de le télécharger, l'amont rend 304, et le cache n'avait donc aucun corps à garder — cette suite-là, et elle seule, manquait hors ligne pendant que ses voisines `-updates` et `-security` sortaient du disque. Une requête conditionnelle sur ce que le cache ne détient pas part désormais sans sa condition, une fois ; et un client qui détient sa propre copie reçoit 304 plutôt que 504 quand l'amont est muet.
- Ce qu'un déploiement hors ligne couvre, exactement : les paquets, les index de dépôts et git. PAS ce que le cache n'a pas le droit de déchiffrer — un client qui porte son propre magasin de confiance, npm et poetry en sont, passe en tunnel opaque, et un tunnel ne porte rien une fois le réseau coupé. Une installation complète d'ERPLibre demande donc toujours le réseau, même si tout ce que le cache détient est servi du disque
- Un miroir est COMPLET là où `repo sync` clone en profondeur un : il coûte donc des dizaines de gigaoctets. Sous dix gigaoctets libres, aucun miroir neuf n'est créé et la requête repart vers l'amont. Le diagnostic dit ce qu'occupent les objets et les miroirs, séparément
- **Déploiement › Cache QEMU › Âge et nettoyage** groupe le cache par âge du dernier usage (jour, semaine ou mois ; objets et dépôts git séparément) et rend ce qui n'a plus servi depuis un délai choisi, ou tout. Un objet servi voit sa date remise à jour : « vieux » veut donc dire « n'a plus servi ». Les deux nettoyages disent ce qui partirait avant d'effacer quoi que ce soit, et l'entrée 5 liste les miroirs du plus lourd au plus léger pour en effacer un
- `long_test/qemu_cache.py` mesure si le cache sert vraiment la seconde VM, et `--hors-ligne` coupe l'amont du seul service du cache pour prouver qu'une troisième se bâtit encore sur l'index stocké
- Avant de couper, le formulaire dit si le cache détient la suite de base de chaque système demandé : F5 prévient « le cache ne détient rien pour ubuntu 26.04 » et un second F5 passe outre. Le verdict n'est rendu que là où une version se nomme sans ambiguïté dans l'URL — les familles apt — plutôt que de rassurer à tort ailleurs. Le verdict est rendu composant par composant — `main`, `universe`, `restricted`, `multiverse`, sur la suite de base et sur ses compagnes `-updates` et `-security` —, car une seule URL en réserve le rendait muet quand un composant entier manquait, et apt ne le disait que vingt minutes plus tard, par « Unable to locate package »
- **Déploiement › Cache QEMU › L'emporter sur une autre machine** porte le magasin vers un autre hôte ERPLibre en un seul flux — `tar`, compressé, par ssh, sans fichier intermédiaire pour des dizaines de gigaoctets — et rend les fichiers au compte du service à l'arrivée, le même compte portant rarement le même numéro sur deux machines. Seul le MAGASIN voyage : un objet est rangé sous son URL et jamais sous la machine qui l'a pris, et un miroir git est un dépôt. Les réglages restent — pont, sous-réseau et autorité appartiennent à l'hôte, et l'entrée 1 les pose là-bas
- Le formulaire de déploiement porte une section **Réseau** avec « Sans connexion internet » : pour tout le déploiement, installation comprise, le service du cache perd sa sortie ET les VM perdent la leur — ping, autres ports, UDP, IPv6 —, si bien qu'un pas qui prendrait un autre chemin que le cache échoue au lieu de réussir en ligne sans rien dire. Les noms ne se résolvent plus par l'internet non plus : l'hôte répond lui-même à tout nom une adresse que le cache intercepte, si bien que seul ce que le cache détient est joignable ; dnsmasq doit être installé sur l'hôte. Une VM derrière le cache tire d'un seul miroir apt, fixe : la recherche de miroir de cloud-init écarte tout miroir derrière un résolveur qui répond à tout nom, et retomberait sur un autre miroir que celui dont les VM précédentes ont rempli le cache. La coupure refuse au lieu de jeter : une adresse que le cache ne détient pas répond 504 sur-le-champ, et non après un délai de connexion ; un noyau qui ne peut pas charger le module du refus reçoit le jeu qui jette. Offerte seulement là où le cache tourne, et le déploiement refuse plutôt que de partir avec l'amont debout, une VM bâtie ainsi réussissant pour la mauvaise raison. **Proxmox VE** porte la même case, offerte là où son hôte est lui-même une VM de ce pont : ses invités sortent derrière son adresse, si bien que la coupure locale les couvre et que rien n'est posé sur l'hôte distant. Un hôte Proxmox qui ne vit pas ici ne la reçoit jamais — rien ici ne sait couper sa sortie
- Un déploiement Proxmox VE peut demander l'**accélération 3D**. La VM est créée avec un écran accéléré (`--vga virtio-gl`) plutôt que la console série comme affichage, et le compte entre dans les groupes du GPU DANS l'invité : le nœud de rendu appartient à « root:render », si bien que sans eux toute application GL retombe en rendu logiciel alors que la négociation VIRGL a réussi, et rien ne le signale. La case n'est offerte que là où l'hôte distant a le nœud de rendu ET les trois bibliothèques que Proxmox charge pour cet écran — VIRGL, GL et EGL. Il nomme celles qui manquent et refuse de démarrer la machine, une fois son disque écrit et sa configuration posée : un hôte portant GL sans EGL échouerait donc à la toute dernière étape. Là où une pièce manque, le formulaire dit laquelle et quel paquet poser sur l'hôte — une case qui disparaît sans un mot se lit comme une régression. Un bouton les pose sans quitter l'écran — le formulaire rend le terminal pour que sudo puisse demander un mot de passe et qu'on voie apt travailler —, puis relit l'hôte au lieu de croire apt sur parole, et la case prend la place du message. Le port série reste posé, donc « qm terminal » fonctionne toujours
- Hors ligne, le cache rejoue ce qu'un passage en ligne a vu, et non plus les seuls corps en 200 : redirections, refus définitifs (404/410) et réponses HEAD des adresses volatiles sont gardés sans corps, sous des clés à eux, et servis SEULEMENT quand l'amont est muet. Un client TUF qui sonde la version suivante de sa racine reçoit le 404 qu'il attend au lieu d'un 504 : mise pose Python hors ligne, vérification Sigstore intacte ; les extensions GNOME, l'installateur de Claude Code et la version de rtk suivent leurs redirections hors ligne
- La coupure hors ligne tombe avec la dernière installation, et non à la fermeture du suivi : une unité root, qui reçoit la levée au lancement, attend le marqueur de fin de chaque installation et survit au suivi fermé tôt, à todo.py tué ou au terminal perdu — 12 h au plus. Le suivi est donc obligatoire hors ligne. Un second déploiement hors ligne est refusé pendant qu'un premier tourne, et un déploiement en ligne lancé entre-temps est prévenu qu'il tournerait hors ligne
- F5 lit aussi les essais hors ligne précédents de la même VM et prévient « au moins N adresses ont manqué », moins ce que le magasin détient désormais (`erplibre_go_qemu_cache --detient`, en lecture seule, sans root). **Déploiement › Cache QEMU › Combler ce qui a manqué hors ligne** les rejoue en ligne, à travers le cache
- Le journal d'installation nomme le commit que la VM exécute ; hors ligne, le récapitulatif dit, branche par branche, quel commit le miroir du cache donnera
- `long_test/qemu_cache.py --distro tous` (ou une liste séparée par des virgules) enchaîne une campagne par système du catalogue, défait les VM de chaque système avant le suivant, et finit sur un tableau des verdicts, durées et octets d'amont. Un échec n'arrête pas la série
- Le cache de téléchargement QEMU peut se nettoyer chaque jour : par âge (`EL_PURGE_AGE`, ex. `90j`) et par plafond de taille (`EL_MAX_SIZE`, ex. `50G`, le moins récemment servi partant d'abord, objets et miroirs git confondus). Les deux sont désactivés par défaut et se règlent depuis **Déploiement › Cache QEMU › Nettoyage automatique**, qui montre ce qui partirait ; `--purge-to-size` applique le plafond à la main. Une réinstallation garde les valeurs choisies
- NixOS 25.11 parmi les systèmes déployables, à côté des huit autres. C'est le seul dont aucune distribution ne publie d'image cloud : l'image est rebâtie par un tiers, donc sa version est épinglée, sa somme sha256 vérifiée à chaque téléchargement, et son origine dite avant que rien ne soit créé. cloud-init n'y reçoit aucune configuration réseau — son moteur networkd prend la clé d'un bloc pour un NOM d'interface, là où netplan honore un `match:` — et le compte y est créé avec `/bin/sh`, sshd refusant un compte dont le shell n'existe pas
- ERPLibre installé sur NixOS, ses dépendances DÉCLARÉES dans `conf/nixos/erplibre.nix` puis appliquées par `nixos-rebuild`, là où les quatre autres familles les installent commande par commande. `services.envfs` répond à `/usr/bin/env` et `programs.nix-ld` donne aux roues manylinux le chargeur dynamique qu'elles réclament ; les en-têtes de ce qui n'a pas de roue sont liés au profil du système, et leurs bibliothèques vont aussi au chargeur, un module compilé sur la machine ne portant pas de RPATH. L'installation l'atteint depuis le menu comme toute autre distribution : l'amorçage pose git, make et python3 — absents de cette image — dans le profil de l'utilisateur pour la durée du clone, et « make install_os » les redéclare pour le système. Vérifié sur une VM : le verrou de 362 paquets s'installe et Odoo répond en HTTP
- Une option `nix + nixos-anywhere` sur les AUTRES distributions, l'inverse de choisir NixOS : elle laisse une VM ordinaire capable d'installer NixOS sur toute machine joignable en SSH. Nix est appelé par son chemin absolu, le PATH du shell distant étant figé avant que l'installateur ne pose le binaire, et les fonctions des flakes sont redonnées sur la ligne de commande, l'écriture de `nix.conf` réclamant un sudo qui peut manquer
- NixOS se déploie sur un hôte **Proxmox** comme sur QEMU/KVM, ce qui a demandé trois correctifs qu'aucune lecture de code n'aurait trouvés. Son image n'a pas de secteur d'amorçage BIOS : une VM créée en SeaBIOS se déclare « running » avec une console muette, donc le catalogue marque désormais les images qui exigent l'UEFI — un marqueur par distribution, Debian 13 démarrant en SeaBIOS sur ce même hôte. `--ciuser` et `--sshkeys` s'en remettent au compte par DÉFAUT de l'image, que NixOS nomme autrement : le cloud-config du dépôt part maintenant comme extrait pour toutes les distributions, avec son bloc `users:` explicite. Et le lecteur cloud-init passe sur le bus SCSI — une image bâtie pour virtio seul n'a pas de pilote ATA et ne voit jamais un lecteur IDE, si bien que cloud-init cherchait des sources réseau et que la VM arrivait sans aucun compte. Vérifié de bout en bout : NixOS rend `/bin/sh`, Debian 13 `/bin/bash`, sudo aux deux
- L'image tierce est vérifiée contre la somme que le dépôt épingle pour elle sur le chemin Proxmox aussi, où un `wget` nu suffisait. Un seul accesseur porte cette somme pour les deux chemins, et le contrôle vaut même pour une image déjà en cache — le cas visé est un fichier substitué ou tronqué entre deux déploiements, qu'un test de présence ne voit pas
- Une entrée du cache de téléchargement peut être retirée, par son URL. Une somme qui ne correspond pas n'invalidait rien : le magasin continuait de servir les mêmes octets, et retélécharger ne changeait rien puisque c'est lui qui répond. Aucune des deux purges ne l'atteint — `--purge` efface tout, et `--purge-older-than` saute ce qui est récent alors que chaque service remet cette date, si bien qu'un objet empoisonné qui sert ne vieillit jamais. `--oublie` est le symétrique de `--detient` : mêmes lignes en entrée, mêmes fonctions de clé, mêmes refus, et un objet présent qui résiste est dit refusé plutôt qu'oublié. Les deux échecs de somme le nomment désormais, avec l'URL exacte
- Le journal d'installation porte ce que l'hôte a décidé avant de lancer : l'autorité du cache de téléchargement posée ou refusée, l'exception, le miroir. Ces lignes se disaient sur une console qui défile, pendant que le fichier qu'on rouvre après un échec ne portait que le symptôme — sur un invité sans magasin de confiance, un certificat refusé, des centaines de dérivations à construire et six cents lignes d'erreurs, sans un mot sur la cause
- Une entrée du cache de téléchargement s'oublie depuis le menu, sous « Âge et nettoyage ». Le binaire savait déjà le faire ; le menu n'offrait que les deux purges en gros, dont aucune ne vise un objet — « effacer ce qui n'a plus servi » n'atteint jamais celui que le service rajeunit chaque fois qu'il le rend, et « tout effacer » coûte le cache entier pour un fichier. `--detient` passe d'abord et fait l'aperçu : même ligne, même clé, sans rien modifier

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- `Assistant › [1]` no longer sends every question to a single remote API on a fixed model: it asks whichever server is configured, and falls back to the remote one only when no local server answers
- The comment hygiene check reads Go comments, not only `#` ones: `//` outside a string, the raw string between backticks, and `/* … */` blocks
- Debian and Ubuntu `by-hash` index files are served from disk, their name being the digest of their content; `…/releases/latest/download/…` is no longer pinned to the first version seen
- An upstream that refuses or drops connections is remembered for 20 s: a request with a stored answer is served at once instead of waiting its connect timeout, which made up most of an offline install's time; a request with nothing stored still tries upstream. A git mirror skips its refresh while its forge is unreachable
- Mirror prefetch runs under the cache's service account, never as root
- The long-test menu asks before creating real machines, and asks again, in words of its own, before `--detruire` removes machines with their disks. The command is shown first, which is what makes the question answerable; a dry run or a performance report creates nothing and asks nothing
- Every entry of the Proxmox VE menu carries an icon, the same picture meaning the same action as in the other menus of the tool
- The QEMU cache binary speaks English or French: service journal, `--status`, `--age`, option help and the error served to a VM. The language comes from `--lang`, then `EL_LANG`, then French; the installer writes `EL_LANG` to the service settings and the TODO menu passes its own. Rules, verdict codes and JSON keys are never translated
- A repository index the cache already holds is revalidated with its ETag rather than downloaded again: upstream still judges every request, and a « 304 » serves the stored body from disk. On a full ERPLibre install the pip indexes, npm metadata and repo bundle had been about 110 MB per VM, taken whole each time. An index stored without its host — shared by every mirror of a rotating list — and an answer carrying no ETag are taken whole as before; the access log names the new outcome `revalidated`
- A registry page served under `Vary: Accept` keeps one copy per representation. npm asks for the same `/npm` page abridged, then complete, then abridged again; kept under one key they replaced each other and the 31 MB were fetched on every install. Each representation is now revalidated and, offline, served on its own; `--detient` still reads the page under its URL alone
- A VM deployed with the cache upstream cut — QEMU form, Proxmox VE, or `deploy_qemu.py --offline` — has npm's security audit turned off (`NPM_CONFIG_AUDIT=false`): it queries a remote service no cache can replay, and failed on every offline install. An online VM keeps its audit
- Verifying a downloaded image no longer needs `--verify`: it runs by default for every distribution that publishes a sum, and `--no-verify` is what skips it — to be kept for offline runs, where a substituted image would otherwise pass unremarked
- `--bios` is refused on an image with no BIOS boot sector, and says why. Forced there, it gave a VM reported « running » with a silent console — the very failure that flag exists to avoid elsewhere

<!-- [fr] -->

- `Assistant › [1]` n'envoie plus chaque question à une seule API distante sur un modèle figé : elle interroge le serveur configuré, et ne retombe sur le distant que lorsqu'aucun serveur local ne répond
- Le contrôle d'hygiène des commentaires lit le Go, et non les seuls `#` : `//` hors d'une chaîne, la chaîne brute entre accents graves, et les blocs `/* … */`
- Les index `by-hash` de Debian et d'Ubuntu sont servis du disque, leur nom étant l'empreinte de leur contenu ; `…/releases/latest/download/…` n'est plus figé sur la première version vue
- Un amont qui refuse ou ignore les connexions est retenu 20 s : une requête qui a une réponse gardée est servie aussitôt au lieu d'attendre son délai d'établissement, qui faisait l'essentiel du temps d'une installation hors ligne ; une requête sans rien en réserve tente toujours l'amont. Un miroir git saute son rafraîchissement tant que sa forge est injoignable
- Le pré-remplissage des miroirs tourne sous le compte du service du cache, jamais en root
- Le menu des tests longs demande avant de créer de vraies machines, et redemande, avec des mots à lui, avant que `--detruire` efface des machines avec leurs disques. La commande est montrée d'abord, c'est elle qui rend la question répondable ; un plan à blanc ou un rapport de performance ne crée rien et ne demande rien
- Chaque entrée du menu Proxmox VE porte une icône, la même image voulant dire la même action que dans les autres menus de l'outil
- Le binaire du cache QEMU parle anglais ou français : journal du service, `--status`, `--age`, aide des options et erreur servie à une VM. La langue vient de `--lang`, puis d'`EL_LANG`, puis du français ; l'installateur écrit `EL_LANG` dans les réglages du service et le menu TODO passe la sienne. Règles, codes de verdict et clés JSON ne se traduisent jamais
- Un index de dépôt que le cache détient déjà est revalidé par son ETag au lieu d'être retéléchargé : l'amont juge toujours chaque requête, et un « 304 » sert le corps gardé depuis le disque. Sur une installation complète d'ERPLibre, les index pip, les métadonnées npm et le bundle de repo pesaient environ 110 Mo par VM, repris en entier à chaque fois. Un index rangé sans son hôte — partagé par tous les miroirs d'une liste qui tourne — et une réponse sans ETag sont repris en entier comme avant ; le journal d'accès nomme la nouvelle issue `revalidated`
- Une page de registre servie sous `Vary: Accept` garde une copie par représentation. npm demande la même page `/npm` abrégée, puis complète, puis de nouveau abrégée ; rangées sous une seule clé, elles se remplaçaient et les 31 Mo repartaient à chaque installation. Chaque représentation est désormais revalidée et, hors ligne, servie à part ; `--detient` lit toujours la page sous sa seule URL
- Une VM déployée l'amont du cache coupé — formulaire QEMU, Proxmox VE, ou `deploy_qemu.py --offline` — a l'audit de sécurité de npm désactivé (`NPM_CONFIG_AUDIT=false`) : il interroge un service qu'aucun cache ne rejoue, et échouait à chaque installation hors ligne. Une VM en ligne garde son audit
- Vérifier une image téléchargée ne demande plus `--verify` : c'est le défaut pour toute distribution qui publie une somme, et `--no-verify` est ce qui la saute — à réserver aux essais hors ligne, où une image substituée passerait autrement sans un mot
- `--bios` est refusé sur une image sans secteur d'amorçage BIOS, et dit pourquoi. Forcé là, il donnait une VM « running » à console muette — la panne même que ce drapeau évite ailleurs

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
- The « - Default » label appears again at the version and environment menus: both reads asked for a capitalised key the version file never writes, and a missing key returns nothing without a word
- The cache's « nothing in store » message is inert as a shell script, every line being a comment. Fed to an installer built on `curl … | bash`, it used to become a cascade of « command not found » that hid the real cause. Such a download now also asks curl to fail on an HTTP error rather than execute the error page
- The wait for a VM to be ready now covers the guest-agent install too. That one is launched as a DETACHED unit so cloud-init returns in seconds, and it runs an `apt-get update`: `cloud-init status --wait` said « done » while the package lock was still held, the next step burnt through its retries, and the install then ran on an index never refreshed — « Unable to locate package », a message that blames the repository rather than the lock. An update that never succeeds now says so on the spot
- A desktop install no longer waits minutes on the apt lock: the apt-daily SERVICE is stopped and not only its timer, a timer being disabled without interrupting the apt-get it already started; and the retry comes back every two seconds rather than every ten, `DPkg::Lock::Timeout` not covering the list lock at all
- Fedora VMs boot again: the firmware loads and starts their loader, then freezes without writing a byte — no console, no DHCP lease, a machine "running" that does nothing. Fedora is booted in legacy BIOS, where the same image starts its kernel; `--bios` still wins when asked
- A VM receives a hostname it can accept — an underscore, which a libvirt domain name tolerates, made it keep its image's generic name — and a timezone its own distribution knows, a legacy alias having left it in UTC
- starship installs in a VM: its installer runs as root, bounded by a root timeout, so it never reaches the `sudo -v` that sudo-rs refuses; its shell hook no longer prints « command not found », nor fails a sourced rc, when starship is absent
- Each optional tool says whether it was installed, and a GNOME extension whose download failed is no longer reported as unavailable for this GNOME
- mise, pyenv and GNOME extensions are downloaded, then run: without pipefail, `curl | sh` could neither report a failed download nor reach its fallback
- The guest-agent unit no longer ends in failure after a successful install
- The cache answers 508 to a request that targets the cache itself, instead of calling itself until it runs out of descriptors
- The cache diagnosis no longer reports a stopped service as running
- The wait for `apt-get update` is bounded by a deadline rather than by a number of attempts. An attempt fails in under a second on a held lock, but takes minutes when the cache answers 504 on every index it does not hold: sixty attempts were then worth hours of silence where five minutes were promised, and the install went on to fail on unmet dependencies
- A Proxmox guest is pinned to the same apt mirror as the rest of the fleet, written over ssh before anything downloads. The store keys its indexes by HOST, so a VM left on the default repositories of its image found none of what the cache had been filled with — offline, every one of those indexes was missing
- The cache installer accepts a bridge and a subnet given by hand. It probed libvirt first and died on « network default not found », so the workaround its own header advertised — `EL_BRIDGE` and `EL_SUBNET` — could never be reached. A machine whose libvirt network is not started, or which carries its bridge otherwise, can now lay the cache down by naming it; and when the probe does run and fails, it names both ways out
- **Deployment › QEMU cache › Install or reinstall** no longer announces « installed and started » when the installer failed. It caught exceptions only: a non-zero exit — a missing libvirt network, a build that gave way — printed the success line right under the error itself, along with the path of an authority that does not exist
- A Proxmox guest receives its guide, its timezone, its apt mirror and the cache authority again. All four go by ssh and used to start as soon as an address was known, while cloud-init was still creating accounts and keys: they failed together, and the VM was born in UTC, guideless, without the authority and on its image's repositories. The deployment now waits for the machine to answer ssh — five minutes at most — and says so when it never does, rather than failing four times in a row
- The cache no longer serves a repository index newer than the signature that announces it. Offline, each object came out with its own date: an index refreshed on Saturday under a Friday `InRelease` made apt fail on « File has unexpected size » or « Hash Sum mismatch », and the install stopped on unmet dependencies — a message that blames the repository, never the cache. The comparison is made on the upstream `Last-Modified`, never on the storage date, which is renewed on every hit
- The refusal to copy the cache to another machine names the gesture that lifts it, and that gesture is not entry 1 — entry 1 installs the cache HERE, so following it reinstalled the host that already had one while the target stayed empty. Three situations were reported as a single « no cache installed »: an ssh link that never ran the probe, a target carrying no cache, and a target whose cache lacks its service account. Each has its own message now, and the missing-cache one lists the steps to run ON the target, the two ways past an installer that reads the « default » libvirt network included — start libvirt, or name the bridge, a stopped libvirt making it die on a network that exists. The steps also name the branch to put the target on, read from this host: the installer is a file of the repository, so a machine left on another branch answers « no such file », which looks nothing like a missing cache. A fourth case is checked before a single byte leaves: sudo asking for a password on the target, which no terminal can answer since the store itself occupies ssh's standard input — the message gives the ticket to obtain there first. The arrival is asked for the privilege ONCE, `tar` and `chown` under a single invocation. Where sudo there wants a password, the entry offers two ways out instead of failing: the one-off sudoers line that allows it, or a two-step mode — the store is sent into the target's own account, which needs no privilege at all, and a printed command extracts it from a terminal there, where a password can be typed. That mode needs twice the store on the target, checked before a byte leaves, a cache holding only already-compressed packages and git archives. The guide carries the same section
- The Proxmox VE deployment form checks the cache before cutting the network, as the libvirt one already did: what the store lacks, no cut VM will read, and the failure used to land an hour later, at the desktop step — a message that blames the repository, never the cache. F5 again means going ahead anyway. Both forms now share a single verdict instead of two copies of it, which would have drifted apart at the first adjustment
- The cache keeps its repository indexes when a mirror list rotates. An index published under the hash of its content — `by-hash/SHA256/…` — was stored under a key carrying the host, so the same bytes served by a second mirror were fetched again; offline they were simply missing, and the install failed on files the store already held, with a message that blames the repository. Such an object is now keyed by its path alone, its name BEING the checksum of its content
- The cache diagnosis no longer reports « no redirection rule is posted » when it simply could not read them. On a host whose sudo asks for a password, `sudo -n nft` returns nothing, and that silence was read as an absence of rules — sending the operator to reinstall a cache that was redirecting correctly. The reading now carries a third state, « cannot tell », marked with a dot rather than a cross, exactly as the upstream-cut reading already did
- A lifted cut gives the upstreams their chance back at once. The service remembers, for a short while, which upstreams just failed to connect, so that an offline install does not pay the connection delay hundreds of times; nothing told it the cut was over, and the first requests after the lift fell back on the store while the network was already back. The lift now touches a witness file inside the store, which that memory consults — there is no channel at all to the running service
- Before cutting, the form also warns about what no index can reveal: a package the deployment lays down OUTSIDE the watched thread — the guest agent, installed by a detached unit whose failure surfaces nowhere — and the git repositories declared by the manifests that have no mirror yet. A held suite index was enough to call the cache complete while not one byte of that package had ever crossed it; and a git negotiation is never stored, so a repository without a mirror simply cannot be cloned once the network is gone
- The mirror warning counts only the repositories of the Odoo version being deployed. It used to add up every manifest in the repository — the deprecated one included — and announced 170 missing mirrors where a real Odoo 18 deployment meets four: an alarm that fires for nothing is one that stops being read. Filling the mirrors still takes every version ahead, which is its purpose
- A host banned from decryption on a burst of transport errors gets another chance. Three failed handshakes in a row put it in an opaque tunnel, and a tunnel never consults the store: a distribution mirror condemned by a few corrupted records sent all its traffic back upstream, including the hundreds of objects already held for it, until the service was restarted. A TLS alert still bans for good — the client looked at our certificate and refused it — but a repeated cut is only a suspicion, and it reopens after ten minutes
- **Deployment › QEMU cache › Git mirrors** fills the base of the active Odoo version, or its extra modules, on their own — beside the full fill of every manifest, which takes hours. Each list shows how many repositories it declares and how many still lack a mirror. What a deployment clones is now read with the manifest merge's own rule and lists, so the extra modules, installed only on request, and the mobile project no longer count: the offline warning announced four missing mirrors that a default Odoo 18 install never clones
- pip's PEP 658 metadata — the `.whl.metadata` file fetched before each wheel — is served from disk. The name ends in `.metadata`, which no rule knew, so each file was taken again on every install: 178 of them on a full ERPLibre install. Copies stored before this change are not reached again; the next online install refills them
- The timezone a deployed VM inherits from its host is translated to its canonical name. Ubuntu 24.04 cloud images no longer carry the legacy aliases — `Canada/*`, `US/*`, `Asia/Calcutta` — moved to a `tzdata-legacy` package they do not install: cloud-init refused the zone, the VM stayed on UTC, and the only sign was cloud-init reporting an error, the offset showing up in timestamps long afterwards. The alias table is the host's own `tzdata.zi`, not a copy kept in the code
- `make` looks for bash instead of assuming `/bin/bash`. That path does not exist on NixOS, where the shell lives in the store, and make stopped before running any recipe — including the one that installs what creates that path. Elsewhere the resolved shell is the same one as before
- The locale and the keyboard a deployed VM is given now apply on Debian, where both silently failed. A locale is generated from `/etc/locale.gen` and nowhere else, so `update-locale` refused one that was not there and the VM stayed on C.UTF-8; the keyboard module ends on a `console-setup` the genericcloud image does not carry, so `/etc/default/keyboard` — the file localed and X read — is written directly instead. Every Debian deployment used to print `cloud-init: status: error`, and a word that always shows warns of nothing
- A guest with no per-file trust anchor is taken out of the download cache instead of being intercepted without one. Interception is transparent and covers the whole bridge, so a VM given no authority still fails every HTTPS download on « self-signed certificate in certificate chain » — and on a declarative system placing the authority comes too late, the first rebuild being the first download. On a Proxmox host it is the HOST that is exempted: a nested guest leaves masqueraded behind it and the bridge never sees its own address. Measured from inside the guest: code 000 and SSL verification 19, then 200 and 0. Without it the package manager fell back to building 564 derivations, whose sources failed for the same reason
- Odoo answers from outside a NixOS VM. It listened on 0.0.0.0:8069 and replied locally, but NixOS enables a firewall by default where none of the four other cloud images does: the host received nothing — not a refusal, silence until the timeout — and the monitor declared Odoo absent on a machine where it was running. Measured from the host: 000 after 12 s, then 303 in 9 ms
- ERPLibre runs as a service on NixOS. The install ended by writing a unit into `/etc/systemd/system`, generated from the store and mounted read-only: it returned 1 at its last step, after the clone, the venv and an Odoo start had all succeeded. The unit is now declared by the module; its interpreter comes from the store, `/bin` being an envfs FUSE mount that systemd does not see when it resolves the executable; and its PATH carries bash, whose absence stopped `run.sh` before Odoo
- What a declarative system must declare, and the four others receive free from their cloud image: xmlsec1, without which Odoo refuses to install auth_saml, a module of the addons path; parallel and shfmt, called by bare name; growpart, absent from the whole system while the disk grow is written « … || true » and returned 0 without growing anything; and the guest agent, which came from the image rather than the repository, its unit PATH lacking findmnt so that guest-exec died with 127 on its first line
- The connection guide is displayed on NixOS. Deployment writes `/etc/motd` everywhere and relies on pam_motd to show it — true of the four cloud images, false here, where sshd reports « printmotd no » and the PAM stack holds no pam_motd: the guide was written, complete, and nobody read it. It also gains a NixOS block naming the trap it exists for — `/etc/nixos/erplibre.nix` is rewritten by `make install_os`, and declarations added there vanish without a word
- « make db_drop_all » no longer announces databases as dropped that were not. It built a parallel command, discarded its exit status and printed the list; the case is reachable as soon as parallel is missing from the PATH, and the operator moves on believing their databases are gone
- A download cache mirror refused for lack of space names its threshold and its measurement. It echoed a field every ordinary caller leaves at zero — « less than 0 B free on disk » announces no threshold and does not say what was measured
- A downloaded image is checked against the sum its publisher ships, for every distribution that publishes one and WITHOUT asking. The check existed behind a flag and for Ubuntu only, so the other images arrived with nothing looking at them. Six now enter, read off the repositories rather than guessed: Debian publishes sha512 where everything else is sha256, the RHEL families name the file « CHECKSUM », Rocky writes the BSD form, and Arch and openSUSE ship a sum per image. An unreachable sums file no longer stops a deployment — that is an availability failure — while a mismatch still stops everything and removes the image
- The locale a deployed VM is given applies on NixOS. cloud-init applies it through locale-gen and update-locale, absent there, and the VM kept the distribution's default — « fr_CA.UTF-8 » asked for, « en_US.UTF-8 » obtained. Both it and the timezone are declared by the module now, and neither is imposed on a NixOS one already had

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
- L'étiquette « - Default » reparaît aux menus des versions et des environnements : les deux lectures demandaient une clé à majuscule que le fichier des versions n'écrit pas, et une clé absente ne rend rien sans rien dire
- Le message « rien en réserve » du cache est inerte pour un interpréteur de commandes, chaque ligne étant un commentaire. Livré à un installateur bâti sur `curl … | bash`, il devenait une cascade de « command not found » qui masquait la cause. Un tel téléchargement demande en outre à curl d'échouer sur une erreur HTTP plutôt que d'exécuter la page d'erreur
- L'attente qu'une VM soit prête couvre aussi la pose de l'agent invité. Celle-ci part en unité DÉTACHÉE pour que cloud-init rende la main en quelques secondes, et elle fait un `apt-get update` : « cloud-init status --wait » disait « done » alors que le verrou des paquets était encore tenu, l'étape suivante épuisait ses reprises, puis installait sur un index jamais rafraîchi — « Impossible de trouver le paquet », un message qui accuse le dépôt et non le verrou. Un update qui n'aboutit pas le dit désormais sur le champ
- Une installation de bureau n'attend plus des minutes sur le verrou apt : le SERVICE apt-daily est arrêté et non son seul minuteur, un minuteur désactivé n'interrompant pas l'apt-get qu'il a déjà lancé ; et la reprise repasse toutes les deux secondes au lieu de dix, « DPkg::Lock::Timeout » ne couvrant pas ce verrou-là
- Les VM Fedora démarrent de nouveau : le micrologiciel charge et démarre leur chargeur, puis se fige sans écrire un octet — pas de console, pas de bail DHCP, une machine « en cours d'exécution » qui ne fait rien. Fedora est amorcée en BIOS hérité, où la même image démarre son noyau ; `--bios` garde le dernier mot
- Une VM reçoit un nom d'hôte qu'elle accepte — un souligné, que le nom de domaine libvirt tolère, lui faisait garder le nom générique de son image — et un fuseau que sa distribution connaît, un alias hérité la laissant en UTC
- starship s'installe dans une VM : son installateur tourne en root, borné par un délai root, et n'atteint jamais le `sudo -v` que sudo-rs refuse ; son crochet de shell n'écrit plus « command not found », ni ne fait échouer un rc sourcé, quand starship est absent
- Chaque outil optionnel dit s'il a été posé, et une extension GNOME dont le téléchargement a échoué n'est plus déclarée indisponible pour ce GNOME
- mise, pyenv et les extensions GNOME sont téléchargés, puis exécutés : sans pipefail, `curl | sh` ne pouvait ni signaler un téléchargement raté ni atteindre son repli
- L'unité de l'agent invité ne finit plus en échec après une pose réussie
- Le cache répond 508 à une requête qui le vise lui-même, au lieu de s'appeler jusqu'à épuiser ses descripteurs
- Le diagnostic du cache ne donne plus un service arrêté pour actif
- L'attente d'`apt-get update` est bornée par une échéance et non par un nombre d'essais. Un essai échoue en moins d'une seconde sur un verrou tenu, mais dure des minutes quand le cache rend 504 sur chaque index qu'il ne détient pas : soixante essais valaient alors des heures de silence là où cinq minutes étaient promises, et l'installation échouait ensuite sur des dépendances introuvables
- Un invité Proxmox est fixé sur le même miroir apt que le reste du parc, écrit par ssh avant tout téléchargement. Le magasin range ses index par HÔTE : une VM restée sur les dépôts par défaut de son image ne retrouvait rien de ce dont le cache avait été rempli — hors ligne, chacun de ces index manquait
- L'installateur du cache accepte un pont et un sous-réseau donnés à la main. Il sondait libvirt d'abord et mourait sur « réseau default introuvable » : le contournement annoncé dans son propre en-tête — `EL_BRIDGE` et `EL_SUBNET` — était donc hors d'atteinte. Une machine dont le réseau libvirt n'est pas démarré, ou qui porte son pont autrement, peut désormais poser le cache en le nommant ; et quand la sonde tourne et échoue, elle nomme les deux issues
- **Déploiement › Cache QEMU › Installer ou réinstaller** n'annonce plus « installé et démarré » quand l'installateur a échoué. Il n'attrapait que les exceptions : un code de sortie non nul — réseau libvirt absent, compilation qui cède — imprimait la ligne de réussite juste sous l'erreur elle-même, avec le chemin d'une autorité qui n'existe pas
- Un invité Proxmox reçoit de nouveau son guide, son fuseau, son miroir apt et l'autorité du cache. Ces quatre gestes passent par ssh et partaient dès qu'une adresse était connue, pendant que cloud-init posait encore les comptes et les clés : ils échouaient ensemble, et la VM naissait en UTC, sans guide, sans autorité et sur les dépôts de son image. Le déploiement attend désormais que la machine réponde en ssh — cinq minutes au plus — et le dit quand elle ne répond jamais, au lieu d'échouer quatre fois de suite
- Le cache ne sert plus un index de dépôt plus récent que la signature qui l'annonce. Hors ligne, chaque objet sortait avec sa propre date : un index rafraîchi samedi sous un `InRelease` de vendredi faisait échouer apt sur « File has unexpected size » ou « Hash Sum mismatch », et l'installation s'arrêtait sur des dépendances introuvables — un message qui accuse le dépôt, jamais le cache. La comparaison porte sur le `Last-Modified` de l'amont, jamais sur la date de stockage, renouvelée à chaque service
- Le refus d'emporter le cache sur une autre machine nomme le geste qui le lève, et ce geste n'est pas l'entrée 1 — elle pose le cache ICI, si bien que la suivre faisait réinstaller l'hôte qui en avait déjà un pendant que l'arrivée restait sans rien. Trois situations étaient rendues par un seul « pas de cache » : un lien ssh qui n'a jamais exécuté la sonde, une arrivée sans cache, une arrivée dont le cache n'a pas son compte de service. Chacune a désormais son message, et celle du cache absent énumère les gestes à faire SUR l'arrivée, avec les deux issues d'un installateur qui lit le réseau libvirt « default » — lever libvirt, ou nommer le pont, un libvirt arrêté le faisant mourir sur un réseau qui existe. Les gestes nomment aussi la branche à donner à l'arrivée, lue sur cet hôte : l'installateur est un fichier du dépôt, si bien qu'une machine restée sur une autre branche répond « fichier introuvable », ce qui ne ressemble en rien à un cache absent. Un quatrième cas est éprouvé avant qu'un seul octet ne parte : un sudo qui réclame un mot de passe à l'arrivée, auquel aucun terminal ne peut répondre puisque le magasin occupe lui-même l'entrée standard de ssh — le message donne le ticket à y obtenir d'abord. Le privilège n'est demandé qu'UNE fois à l'arrivée, « tar » et « chown » sous une seule invocation. Quand le sudo de là-bas réclame un mot de passe, l'entrée offre deux issues au lieu d'échouer : la ligne sudoers à poser une fois, ou un mode en deux temps — le magasin part dans le compte de l'arrivée, qui n'exige aucun privilège, et une commande affichée l'extrait depuis un terminal de là-bas, où un mot de passe se tape. Ce mode réclame deux fois le magasin à l'arrivée, vérifié avant qu'un octet ne parte, un cache ne contenant que des paquets et des archives git déjà comprimés. Le guide porte la même section
- Le formulaire de déploiement Proxmox VE éprouve le cache avant de couper le réseau, comme celui de libvirt le faisait déjà : ce que le magasin n'a pas, aucune VM coupée ne le lira, et l'échec tombait une heure plus tard, à la pose du bureau — un message qui accuse le dépôt, jamais le cache. F5 à nouveau vaut passage outre. Les deux formulaires partagent désormais un seul verdict au lieu de deux copies, qui auraient divergé au premier ajustement
- Le cache garde ses index de dépôt quand une liste de miroirs tourne. Un index publié sous l'empreinte de son contenu — « by-hash/SHA256/… » — était rangé sous une clé portant l'hôte : les mêmes octets servis par un second miroir étaient repris à l'amont, et hors ligne ils manquaient tout simplement — l'installation échouait sur des fichiers que le magasin détenait, avec un message qui accuse le dépôt. Un tel objet est désormais rangé sous son seul chemin, son nom ÉTANT la somme de son contenu
- Le diagnostic du cache n'annonce plus « aucune règle de détournement n'est posée » quand il n'a simplement pas pu les lire. Sur un hôte dont le sudo réclame un mot de passe, « sudo -n nft » ne rend rien, et ce silence était lu comme une absence de règle — ce qui envoyait réinstaller un cache qui détournait correctement. La lecture porte désormais un troisième état, « impossible de savoir », marqué d'un point et non d'une croix, comme le faisait déjà la lecture de la coupure d'amont
- Une coupure levée rend aussitôt leur chance aux amonts. Le service retient un court moment ceux dont la connexion vient d'échouer, pour qu'une installation hors ligne ne paie pas le délai d'établissement des centaines de fois ; rien ne lui disait que la coupure était finie, et les premières requêtes d'après la levée se rabattaient sur le magasin alors que le réseau était déjà revenu. La levée touche désormais un témoin dans le magasin, que cette mémoire consulte — il n'existe aucun canal vers le service en marche
- Avant de couper, le formulaire avertit aussi de ce qu'aucun index ne peut révéler : un paquet que le déploiement pose HORS du fil observé — l'agent invité, posé par une unité détachée dont l'échec ne remonte nulle part — et les dépôts git déclarés par les manifestes qui n'ont pas encore de miroir. Un index de suite en réserve suffisait à faire passer le cache pour complet alors qu'aucun octet de ce paquet ne l'avait jamais traversé ; et une négociation git ne se garde jamais, si bien qu'un dépôt sans miroir ne peut tout simplement pas être cloné une fois le réseau coupé
- L'avertissement sur les miroirs ne compte que les dépôts de la version d'Odoo déployée. Il additionnait tous les manifestes du dépôt — le déprécié compris — et annonçait 170 miroirs manquants là où un vrai déploiement Odoo 18 en rencontre quatre : une alarme qui sonne pour rien est une alarme qu'on cesse de lire. Le remplissage des miroirs, lui, prend toujours de l'avance pour toutes les versions, ce qui est son rôle
- Un hôte banni du déchiffrement sur une rafale d'erreurs de transport retrouve sa chance. Trois poignées de main manquées d'affilée le passaient en tunnel opaque, et un tunnel ne consulte jamais le magasin : un miroir de distribution condamné par quelques enregistrements corrompus renvoyait tout son trafic à l'amont — y compris les centaines d'objets déjà détenus pour lui — jusqu'au redémarrage du service. Une alerte TLS bannit toujours définitivement, le client ayant regardé notre certificat et l'ayant refusé ; mais une coupure répétée n'est qu'un soupçon, et elle se rouvre au bout de dix minutes
- **Déploiement › Cache QEMU › Miroirs git** remplit à part la base de la version d'Odoo active, ou ses modules extra — à côté du remplissage de tous les manifestes, qui prend des heures. Chaque liste dit combien de dépôts elle déclare et combien n'ont pas encore de miroir. Ce qu'un déploiement clone se lit désormais avec la règle et les listes de la fusion des manifestes elle-même : les modules extra, installés seulement sur demande, et le projet mobile ne comptent plus, là où l'avertissement hors ligne annonçait quatre miroirs manquants qu'une installation Odoo 18 par défaut ne clone jamais
- Les métadonnées PEP 658 de pip — le fichier `.whl.metadata` récupéré avant chaque roue — sont servies du disque. Le nom finit par `.metadata`, qu'aucune règle ne connaissait : chaque fichier repartait à chaque installation, 178 sur une installation complète d'ERPLibre. Les copies gardées avant ce changement ne sont plus atteintes ; la prochaine installation en ligne les remplit
- Le fuseau horaire qu'une VM déployée hérite de son hôte est traduit en son nom canonique. Les images cloud d'Ubuntu 24.04 ne portent plus les alias historiques — `Canada/*`, `US/*`, `Asia/Calcutta` — déplacés dans un paquet `tzdata-legacy` qu'elles n'installent pas : cloud-init refusait le fuseau, la VM restait en UTC, et le seul signe était un cloud-init en erreur, le décalage n'apparaissant qu'aux horodatages longtemps après. La table des alias est le `tzdata.zi` de l'hôte, et non une copie figée dans le code
- `make` cherche bash au lieu de présumer `/bin/bash`. Ce chemin n'existe pas sur NixOS, où le shell vit dans le store, et make s'arrêtait avant d'exécuter la moindre recette — y compris celle qui installe de quoi créer ce chemin. Ailleurs, le shell résolu est celui d'avant
- Le locale et le clavier qu'une VM déployée reçoit s'appliquent désormais sur Debian, où les deux échouaient en silence. Un locale se génère à partir de `/etc/locale.gen` et de nulle part ailleurs : `update-locale` refusait celui qui n'y était pas et la VM restait en C.UTF-8 ; le module clavier finit par un `console-setup` que l'image genericcloud ne porte pas, alors `/etc/default/keyboard` — le fichier que localed et X relisent — est écrit directement. Chaque déploiement Debian imprimait `cloud-init: status: error`, et un mot qui s'affiche toujours n'avertit plus de rien
- Un invité sans ancre de confiance par fichier est soustrait au cache de téléchargement plutôt qu'intercepté sans elle. Le détournement est transparent et vaut pour tout le pont : une VM à qui l'on ne donne pas l'autorité échoue quand même sur « self-signed certificate in certificate chain » — et sur un système déclaratif, poser l'autorité arrive trop tard, la première reconstruction étant le premier téléchargement. Sur un hôte Proxmox, c'est l'HÔTE qui est excepté : un invité imbriqué sort masqué derrière lui et le pont ne voit jamais sa propre adresse. Mesuré depuis l'invité : code 000 et vérification SSL 19, puis 200 et 0. Sans cela le gestionnaire de paquets se rabattait sur 564 dérivations à construire, dont les sources échouaient pour la même raison
- Odoo répond depuis l'extérieur d'une VM NixOS. Il écoutait sur 0.0.0.0:8069 et répondait en local, mais NixOS active un pare-feu par défaut là où aucune des quatre autres images cloud n'en active : l'hôte ne recevait rien — pas un refus, un silence jusqu'au délai — et le suivi déclarait Odoo absent sur une machine où il tournait. Mesuré depuis l'hôte : 000 après 12 s, puis 303 en 9 ms
- ERPLibre tourne comme service sur NixOS. L'installation finissait par écrire une unité dans `/etc/systemd/system`, généré depuis le store et monté en lecture seule : elle rendait 1 à sa dernière étape, après que le clone, le venv et un démarrage d'Odoo avaient tous réussi. L'unité est désormais déclarée par le module ; son interpréteur vient du store, `/bin` étant un montage FUSE d'envfs que systemd ne voit pas quand il résout l'exécutable ; et son PATH porte bash, dont l'absence arrêtait `run.sh` avant Odoo
- Ce qu'un système déclaratif doit déclarer, et que les quatre autres reçoivent gratuitement de leur image cloud : xmlsec1, sans lequel Odoo refuse d'installer auth_saml, module du chemin des addons ; parallel et shfmt, appelés par leur nom nu ; growpart, absent de tout le système alors que l'agrandissement du disque s'écrit « … || true » et rendait 0 sans rien agrandir ; et l'agent invité, qui venait de l'image et non du dépôt, le PATH de son unité manquant findmnt si bien que guest-exec mourait en 127 dès sa première ligne
- Le guide de connexion s'affiche sur NixOS. Le déploiement écrit `/etc/motd` partout et compte sur pam_motd pour le montrer — vrai des quatre images cloud, faux ici, où sshd rend « printmotd no » et où la pile PAM ne contient aucun pam_motd : le guide était écrit, complet, et personne ne le lisait. Il gagne aussi un bloc propre à NixOS, qui nomme le piège pour lequel il existe — `/etc/nixos/erplibre.nix` est réécrit par `make install_os`, et les déclarations qu'on y ajoute disparaissent sans un mot
- « make db_drop_all » n'annonce plus détruites des bases qui ne le sont pas. Il composait une commande parallel, jetait son code de retour et imprimait la liste ; le cas s'atteint dès que parallel manque du PATH, et l'opérateur passe à la suite en croyant ses bases parties
- Un miroir du cache de téléchargement refusé faute de place nomme son seuil et sa mesure. Il reprenait un champ que tout appelant ordinaire laisse à zéro — « moins de 0 o libres sur le disque » n'annonce aucun seuil et ne dit pas ce qui a été mesuré
- Une image téléchargée est vérifiée contre la somme que son éditeur publie, pour toute distribution qui en publie une et SANS le demander. La vérification existait sous un drapeau et pour Ubuntu seulement, si bien que les autres images arrivaient sans que rien ne les regarde. Six y entrent, relevées sur les dépôts plutôt que devinées : Debian publie du sha512 quand tout le reste est en sha256, les familles RHEL nomment le fichier « CHECKSUM », Rocky l'écrit en forme BSD, et Arch comme openSUSE posent une somme par image. Un fichier de sommes injoignable n'arrête plus un déploiement — c'est une panne de disponibilité — quand un écart arrête toujours tout et supprime l'image
- La locale qu'une VM déployée reçoit s'applique sur NixOS. cloud-init l'applique par locale-gen et update-locale, absents là-bas, et la VM gardait le défaut de la distribution — « fr_CA.UTF-8 » demandé, « en_US.UTF-8 » obtenu. Elle et le fuseau sont désormais déclarés par le module, et ni l'un ni l'autre n'est imposé à une NixOS qu'on avait déjà

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
- Following a redirect, the cache no longer forwards the client's credentials (Authorization, Cookie, Proxy-Authorization) to another host

<!-- [fr] -->

- Une clé d'API et un jeton Bearer sont caviardés eux aussi avant qu'une commande soit affichée, journalisée ou réimprimée : `OPENAI_API_KEY=` partait en clair, et un jeton d'en-tête échappait par construction, ne portant ni nom d'option ni nom de variable
- En suivant une redirection, le cache ne transmet plus les identifiants du client (Authorization, Cookie, Proxy-Authorization) à un autre hôte

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
