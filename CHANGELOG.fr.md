
# Journal des modifications

Tous les changements notables de ce projet seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com). Ce projet adhère
au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## Ajouté

- Une section **Réseau** au menu QEMU/KVM, et le script qui la porte, `script/qemu/network_qemu.py`. `--status` lit ce que sert le réseau libvirt, quel pont le porte, quelles VM y sont attachées, ce que disent leurs baux et ce que l'hôte route par ailleurs — rien n'est modifié. `--recreate` remet le sous-réseau sous ces VM en trois gestes ordonnés, et l'ordre EST la fonctionnalité : les VM attachées sont arrêtées D'ABORD, redéfinir un réseau sous une VM vivante lui laissant un bail qui ne mène nulle part et un tap qui n'est plus sur aucun pont ; puis le réseau est redéfini sur le préfixe voulu — 192.168.122 par défaut, celui de libvirt, celui que supposent les entrées ~/.ssh/config et les notes prises avant — et redémarré ; puis exactement les VM qu'il a arrêtées sont rallumées, une VM déjà éteinte le restant. Une VM qui n'obéit pas au shutdown ANNULE la redéfinition plutôt que d'y perdre son pont, et « --force-off » est ce qui lui coupe le courant. Un préfixe visé qui recouvre ce que l'hôte route déjà est refusé : c'est ainsi qu'une machine perd sa propre passerelle au profit d'un pont. Un réseau qui sert déjà le préfixe voulu n'est pas redéfini, et le seul cycle d'arrêt-relance répare encore les taps qu'un réseau abattu a détachés
- Un outil VPN, cinq technologies libres au menu — L2TP/IPsec PSK, WireGuard, OpenVPN, OpenConnect, sshuttle — accessible depuis **TODO › Execute › Réseau › VPN** et depuis la section Déploiement. Ce qui n'est pas secret (hôte, utilisateur, routes, MTU) vit dans une configuration JSON lisible et les clés pré-partagées comme les mots de passe dans un coffre KeePassXC : un profil peut donc être montré, comparé et partagé sans donner de quoi monter le tunnel. Les secrets s'écrivent en tmpfs sous 0700 et jamais sur un disque persistant ; `--dry-run` montre chaque geste privilégié sans en exécuter un, et l'outil tourne sous votre identité, chaque étape appelant sudo d'elle-même. Demander tout le trafic par le tunnel ne coupe plus la session SSH qui vient d'en donner l'ordre — l'adresse de l'opérateur, lue dans `SSH_CONNECTION`, reçoit sa propre route de survie, et toutes sont retirées au démontage. Seul L2TP/IPsec a monté un tunnel contre un concentrateur réel ; les quatre autres portent au choix une étoile disant que seuls des tests unitaires les couvrent
- `diagnose` nomme l'étage fautif du plus bas au plus haut, pour que la première ligne fausse soit la cause et non une conséquence : ce que le noyau expose · les paquets · la vérification propre à la technologie · interface et adresses · chaque route déclarée · une adresse témoin qui ne répond qu'à travers le tunnel · les journaux. L'étage du noyau attrape ce qu'aucune configuration ne rattrape : mettre à jour le paquet du noyau remplace `/lib/modules/<version>` et le noyau qui tourne ne peut plus charger aucun module, si bien que l'IPsec devient indisponible sur un noyau qui le prend en charge, que charon abandonne à l'initialisation et que le symptôme ressort trois étages plus haut en connexion jamais chargée. Le seul remède est un redémarrage, et il est PROPOSÉ, jamais fait : ni à blanc, ni sans terminal pour répondre, et seulement quand la capacité manque ET que les modules ont disparu
- L'accélération 3D des VM QEMU, cochée à la création et réglable ensuite, même sur une VM SANS écran virtuel — « auto » ne l'accorde jamais là, s'abstenant plutôt que de poser un périphérique vidéo que personne n'a demandé, alors qu'un rendu hors écran ou un émulateur tournant dedans veut exactement cela. Un nœud de rendu peut exister sans qu'EGL y démarre : QEMU refuse alors le domaine et la VM reste inutilisable jusqu'à ce que quelqu'un défasse le réglage, d'où un repli sur le rendu logiciel à la création et le retrait proposé sur une VM existante. Dans l'invité, le nœud de rendu appartient à « root:render » en 0660 et le compte n'y était pas : toute application GL retombait sur le rendu logiciel alors que la négociation VIRGL avait réussi, sans que rien ne le signale ; « render » et « video » sont désormais déclarés AVANT usage, un nom de groupe inconnu faisant que cloud-init ne crée aucun compte — ni mot de passe, ni clé SSH, une VM qui démarre injoignable
- Un diagnostic QEMU, écrit dans un fichier unique à transmettre à quelqu'un qui n'a pas accès à la machine : vingt et une sondes en lecture — hôte, hyperviseur, GPU, outils présents, stockage — chacune bornée dans le temps, une commande qui pend ne devant pas retenir le rapport, et chaque section isolée, le fichier s'écrivant d'un bloc à la fin. Il dit l'état 3D de chaque VM d'après sa définition PERSISTANTE, où trois valeurs répondent ensemble et aucune seule : le type de vidéo, « accel3d », et le device figé par libvirt. Ce dernier, un attribut arrivé avec libvirt 12.5.0 pour tenir l'ABI de l'invité stable d'un démarrage à l'autre, L'EMPORTE sur « accel3d » : une VM démarrée une première fois sans 3D garde le device sans GL, et cocher la case ensuite écrit une intention que rien n'applique. Le rapport propose aussi les outils qui lui manquent, la commande complète affichée avant la question, et la liste des périphériques que QEMU peut ouvrir — libvirt y met le nœud de rendu quand le domaine le déclare, jamais les nœuds propres d'une carte propriétaire, que sa pile ouvre pourtant. Il porte le nom de l'hôte, ses chemins et ses adresses, et le dit avant qu'on l'envoie
- La récupération de fichiers dans le disque d'une VM qui ne démarre plus, libguestfs montant son qcow2 sans elle. Toute commande porte « --ro », et c'est ce qui change la manœuvre : ouvrir en écriture le disque d'une machine allumée corrompt son système de fichiers. Les partitions sont listées, puis les répertoires à extraire, les commandes « copy-out » étant montrées plutôt que devinées
- Les assistants de développement installés DANS une VM au déploiement, et la pré-configuration qui permet de s'en servir sans rien retaper : rtk et son hook global de réécriture, starship avec son accroche au shell, un agent — Claude Code ou opencode —, tig, htop et vim, « merge.conflictStyle=zdiff3 », les hooks git du dépôt, les cinq commandes Claude du dépôt, et « source .venv.erplibre/bin/activate » dans l'historique du shell, là où la flèche du haut le retrouve. La case découvre le choix et l'identité git, pré-remplie avec celle de l'hôte, puisque c'est ce que la VM reçoit déjà et qu'un champ vide la ferait croire absente ; ce qui est saisi prime, champ par champ. Chaque pose est privée d'entrée standard et bornée dans le temps : « || true » couvre l'échec, pas l'ATTENTE, et un installateur amont qui pose une question resterait pendu sur un SSH sans terminal — d'où « -y » pour starship. L'option travaille en DEUX temps, et le second est nommé plutôt que tu : les hooks et les gabarits de commandes VIVENT dans le dépôt, si bien qu'une VM qui n'installe rien reçoit les poses et s'entend dire ce que le clone absent lui coûte. « core.editor » n'est posé que là où il n'y en a pas, l'éditeur de l'hôte voyageant déjà jusqu'au ~/.gitconfig de la VM — deux autorités sur un même réglage en font une de trop. Tout ce second temps rend 0 : une pré-configuration est un confort, et l'installation seule porte le verdict de la VM
- L'aide d'une option au formulaire de déploiement, ouverte par « ? » ou F1 et fermée par Esc : ce que chaque réglage d'installation POSE dans la VM, toutes ses étapes plutôt que les deux ou trois que le libellé d'une case peut porter — celle des outils IA en engage huit à elle seule. Le texte vit dans la même table que les cases, si bien qu'une option ajoutée sans aide affiche un bloc vide plutôt qu'un texte faux, et les DEUX écrans le lisent, celui de QEMU/KVM comme celui de Proxmox VE
- Un menu Git et Shell qui installe ce dont un clone a besoin au lieu d'afficher une commande à recopier : les hooks git du dépôt, « merge.conflictStyle=zdiff3 », Starship, Claude Code, opencode, et les plugins Claude Code avec une liste ERPLibre. Trois commandes d'assistant s'y déploient — « /git_prepare_merge », « /todo_plan_max », « /todo_generate_code ». Les outils manquants d'une réduction sûre s'installent sur les quatre familles de paquets, là où trois écritures séparées en connaissaient chacune un sous-ensemble différent. Un binaire posé dans un répertoire du HOME que le PATH du shell ne porte pas toujours est trouvé quand même, et la ligne d'export est écrite une seule fois
- Un déploiement bloqué par un disque orphelin — le qcow2 qu'une création interrompue laisse et que « deploy_qemu » refuse ensuite d'écraser — se voit proposer son effacement, taille et chemin affichés, avant que la création n'échoue après avoir fait attendre
- Un hook `pre-commit` liste les commentaires à relire dans les fichiers qu'on indexe, et ne bloque jamais : sur les sources du dépôt, 373 fichiers rendent 463 signaux, et un contrôle bloquant à cette échelle se fait désinstaller la semaine suivante. L'outil qui le sert, `script/analyse/check_comment_hygiene.py`, rapporte deux familles de sûreté inégale — la donnée identifiante, adresse, courriel ou chemin de compte, qui est une trouvaille ; et le récit, marqueur de témoignage, date absolue ou première personne, qui est un signal à RELIRE, l'outil ne pouvant savoir si la phrase énonce un fait durable. Il lit les commentaires et les docstrings, les lignes `#` comme les commentaires shell de fin de ligne, écarte le code tiers, et se replie sur un balayage ligne à ligne quand un source ne se parse pas, un rapport vide déclarant sinon propre un fichier qu'il n'a jamais lu. Les codes de sortie suivent la convention du dépôt : 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué
- Le menu TODO montre le contexte fourni à un assistant, éparpillé sur six sources : instructions, règles, skills, commandes déployées, hooks git et mémoire. Chaque commande déployée est comparée à son gabarit du dépôt en ignorant les lignes d'identité git que le déploiement substitue, si bien qu'une copie périmée se voit là où une égalité stricte les déclarerait toutes périmées. Rien de `private/` n'est relevé, pas même un compte : nommer un fichier dont l'objet est de retenir ce qui ne doit pas sortir revient à le désigner
- Dupliquer une base et la neutraliser pour de bon : la duplication passe par `exp_duplicate_database` d'Odoo plutôt que par `CREATE DATABASE … TEMPLATE`, qui copie les tables et rien d'autre. Odoo seul coupe les connexions ouvertes sur la source — un shell Odoo laissé ouvert suffit à faire refuser PostgreSQL —, régénère `database.uuid`, copie le filestore et exécute les fichiers `neutralize.sql` des modules installés. Les modules maison du dépôt n'obtenaient aucun des quatre, et l'un d'eux ouvrait une porte : supprimer tous les `ir.mail_server` fait retomber Odoo sur le `smtp_server` du fichier de configuration, là où le serveur bouchon d'Odoo existe précisément pour boucher ce trou. La neutralisation d'Odoo commence à la 16 ; de 12 à 15 la copie retombe sur la technique de longue date du dépôt, `update_prod_to_dev.sh`, qui ne pose pas `is_neutralized`, ne désactive aucun cron et laisse les clés de paiement, mais supprime les serveurs de courriel et pose un compte de développement. Le chemin suivi est ANNONCÉ à l'exécution, une copie dont on ignore par quel chemin elle est passée ne se jugeant pas, et un script introuvable fait échouer la copie plutôt que de la laisser sortir brute en s'annonçant neutralisée
- L'écran de qualité de migration dit si une migration a réussi, là où il comparait seulement les paliers : tous les verdicts s'affichent, de la 12 à la 18 — seule façon de voir qu'un échec a été rattrapé à un palier plus haut — lus dans le journal de progression et rattachés au palier ODOO, non au compteur du pilote, décalé d'un rang. Il dit où vivent les traces, config.conf laissant logfile= vide et la sortie d'Odoo mourant avec le terminal ; il montre le passage du journal d'étape qui entoure chaque commande, garde par tee ce qu'il lance lui-même et le relit sans relancer ; et il lance six étapes de revue par « r », en demandant avant de basculer le checkout, car rejouer un test d'un autre palier ouvrait la base avec la mauvaise version, qui y écrit avant d'échouer. Un statut se lit comme les outils l'écrivent — 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué — si bien que plus rien n'est peint en rouge là où rien n'a échoué. La sortie est capturée par pseudo-terminal, jamais par un tube : smoke_public_url exige stdin ET stdout sur un terminal et, derrière un tube, cesse en silence d'offrir la réparation des vues COW ; neuf exécutions y passent, deux restent dehors, pty.spawn naissant en 0×0 où un plein écran se perdrait
- Trois contrôles rejoignent la revue de migration, chacun pour ce qu'un palier détruit sans signaler le moindre échec. Les trous de manifeste : un dépôt d'addons absent du manifeste d'un palier n'existe pas sur disque pendant cette étape, Odoo déclare donc ses modules introuvables, le pilote propose de les effacer, et la fonctionnalité part avec eux — seul le trou compte, présent avant et après, absent au milieu, ce qui ramène 35 candidats à 19 vraies omissions au lieu de 46 % de bruit. Le type de vue tree, supprimé en Odoo 18 sans conversion, se lit dans les SOURCES, là où tous les autres outils de la revue lisent la base et où un module jamais installé ne laisse rien ; le mot reste un identifiant valide, si bien que sur 465 occurrences 80 seulement cassent, et lxml et ast décident par la position du littéral, jamais une regex. La dérive du plan comptable : une montée de version recharge le gabarit de localisation en silence — trois des scripts l10n du noyau appellent try_loading() sans force_create=False, donc tout compte que le gabarit n'apparie pas par code est CRÉÉ, et les groupes ainsi ajoutés reclassent le plan existant. Un compte absolu n'y dit rien, seul l'ÉCART entre deux paliers d'une même migration se juge, et l'outil prescrit de rejouer le palier plutôt que de réparer : sa clé naturelle de suppression attrape aussi des comptes réappariés par code
- run.sh réveille le registre par HTTP pendant que le serveur démarre. Odoo ne charge le registre d'une base qu'à la PREMIÈRE requête qui la concerne, et sur une base migrée la personne qui ouvre la page attend des dizaines de secondes ; la sonde prend ce temps à sa place et s'arrête à la première réponse, un 303, un 404 ou un 500 prouvant tous que le registre est chargé. Elle ne peut pas nuire : elle rend TOUJOURS 0, meurt avec run.sh par un trap, abandonne après deux minutes, et prend le port sur la ligne de commande, puis dans config.conf, puis dans le journal, exact même quand le port demandé était pris — l'écoute sur une interface vide ou générale est sondée par le bouclage. `--erplibre-disable-warmup-http` la coupe et est le seul drapeau RETIRÉ avant odoo_bin.sh, qu'Odoo refuse ; `--no-http` et `--stop-after-init` la coupent aussi et passent, puisqu'il n'y a rien à réveiller quand personne n'écoute
- Une convention d'écriture pour ce qui reste dans git. Un sujet de commit lu seul, sans diff ni corps, doit dire quelle partie du système change et ce qui y est désormais différent — le symptôme, l'erreur citée et la métaphore sont des PREUVES, et une preuve va dans le corps. Un commentaire a le CODE pour sujet, au présent de ce qu'il fait : une phrase dont le sujet est un incident, une machine, une date ou une personne part vers `tasks/`, non versionné, tandis que le mode de défaillance que le code empêche reste. Rien d'identifiant hors de `private/` — ni client, ni base réelle, ni hôte, ni adresse, ni courriel, ni chemin de compte — et l'exemple qui illustre cet interdit s'invente au lieu de s'emprunter, un test figeant pour toujours ce qu'il contient. Une mesure qui établit un fait durable reste, dépouillée de sa date et de son opérateur ; le relevé de ce qui répondait ce jour-là part
- Un hook `commit-msg` refuse la part mécanique de cette convention d'écriture, et rien de plus : tag absent, sujet de plus de 72 caractères, sujet ouvrant sur une citation, corps de plus de 10 lignes pour une langue, adresse IP, courriel, chemin de compte, terme d'une liste de noms interdits qui vit hors de git puisque c'est elle qu'elle protège — absente, ce dernier contrôle se tait. Il compte des caractères et non des octets, sans quoi un sujet français de 72 caractères tomberait sur ses accents ; il exclut les trailers et le diff de `--cleanup=scissors` ; et son refus nomme `git commit --no-verify`, un garde-fou qui refuse trop étant désinstallé. Dire sur quoi porte le code reste un jugement qu'aucun hook ne rend. Le prédicat qui distingue une adresse du parc d'une version de manifeste Odoo, d'une boucle locale, d'un masque, d'une adresse de réseau ou d'un bloc de documentation RFC 5737 est partagé avec le contrôle des commentaires, deux prédicats pour une même question finissant par diverger. Ses 40 tests pèsent les acceptations — un « Merge branch », un fixup de rebase — autant que les refus
- `long_test/` — des tests qui créent de vraies machines et durent des heures, tenus hors de `test/` pour que le lanceur unitaire reste lançable en quelques secondes. `deep_proxmox.py` empile des Proxmox dans des Proxmox, `deep_qemu.py` des QEMU dans des QEMU, et les deux partagent un moteur. Mesuré sur 28 cœurs : trois étages coûtent 34 minutes, le quatrième 4 h 20 d'amorçage plus 7 h 18 d'installation — tout y est 15 à 30 fois plus lent, et c'est là que les fabricants cessent de documenter l'imbrication. La profondeur est un paramètre et vaut trois par défaut, parce que trois marche
- deep_qemu PROUVE KVM à chaque étage au lieu de le supposer : `deploy_qemu.py` ne passe jamais `--cpu host-passthrough` et, quand /dev/kvm manque, il n'échoue pas — il pose `--virt-type qemu` et crée une VM entièrement ÉMULÉE, sept minutes et demie de démarrage, sans qu'aucun code de retour ne le dise. Sans garde, la descente mesurerait de la TCG empilée en croyant mesurer de l'imbrication. Chaque étage doit montrer `/dev/kvm`, `nested=Y` et un domaine enfant en `type='kvm'` ; ce qui n'a pas été lu vaut NON
- Les deux tests longs acceptent `--hote` pour partir d'une machine qu'on possède déjà, au lieu de créer une VM de tête pour héberger un hyperviseur qu'on a sous la main — cela coûte cinq minutes ET un étage d'imbrication. Le plan se dimensionne alors sur la RACINE, lue par ssh ; les délais comptent la profondeur ABSOLUE ; et la racine n'est jamais un étage atteint, jamais détruite, et son entrée ~/.ssh/config n'est jamais retirée
- Déploiement de VM ERPLibre en QEMU/KVM depuis des images cloud (Ubuntu, Debian, Fedora, AlmaLinux, Rocky Linux, openSUSE Tumbleweed, Arch) en amd64, arm64 et s390x, avec un menu pour lister, tester, redimensionner, supprimer et nettoyer
- VM graphiques : un choix serveur / bureau proposant GNOME ou Cinnamon (le bureau de Linux Mint), avec accès distant par xrdp — TigerVNC sur Arch
- Interfaces Textual : tableau de bord d'installation, formulaire de
  déploiement de VM, écran de reprise de migration ; Textual s'installe à la
  demande
- Télémétrie de navigation pour TODO, en arbre, en kanban ou en liste
- Outils de migration pour les vues copy-on-write du site web : prévoir,
  photographier, comparer, neutraliser et réinitialiser
- Boîte à outils d'analyse en lecture seule d'une base Odoo
- Configuration SSH avec ProxyJump récursif, redirection de port et
  enregistrement des hôtes QEMU dans virt-manager
- Serveur de notifications NTFY auto-hébergé
- Politique d'IA générative, adoptant celle de l'OCA
- Agents et commandes Claude Code
- Serveur git local pour partager du code entre machines
- Tests unitaires pour la configuration, la refactorisation et les composants
  non couverts, avec un plan de test bilingue
- Lecture et envoi de courriel depuis le CLI TODO, en IMAP et SMTP
- L'analyse de base lit un zip de sauvegarde tel quel, sans le restaurer
- Menu de gestion RTK
- Menu d'outils d'assistance IA, avec la commande de commit Claude Code
- Menu de déploiement : cloner ERPLibre sur un hôte distant, configurer sshfs,
  et des cibles make pour le déploiement SSH
- Correctif git, dépôt distant git et configuration vim depuis le menu
- Odoo 18 lit les fichiers STL (OpenCAD)
- Mobile : whisper.cpp et sentencepiece au manifeste, un script de test mobile,
  et le contrat d'API de synchronisation Odoo
- brin_advisor et brin_cluster : recommander et appliquer le bon index
  PostgreSQL pour un modèle Odoo
- Réglages par VM dans le formulaire de déploiement : vCPU, RAM, disque, type, branche ERPLibre, version d'Odoo et fuseau horaire, un verrou qui soustrait une VM au profil global, le renommage, et plusieurs exemplaires d'une entrée
- Fournisseur d'interpréteur Python choisi par EL_PYTHON_PROVIDER — mise pose un CPython précompilé, pyenv en compile un — et retenu par déploiement
- uv pose les paquets Python, pip en repli, par EL_PIP_PROVIDER
- openSUSE Leap 16.0 et Fedora 43 au catalogue de VM
- Magasin d'applications d'une VM graphique : .deb seul, outillage Flatpak, ou snap
- Tunnel vers le bureau distant : la commande SSH est composée depuis ~/.ssh/config, avec la console de l'hyperviseur comme troisième voie
- Le tableau de bord d'installation agit sur une VM sans la quitter : mise à jour par parties, redémarrage d'Odoo, suppression ; colonne d'architecture et colonnes ajustables
- Migration : revenir à une étape depuis l'écran de reprise ou depuis une invite, et agir sur les copies COW dès leur annonce
- L'analyse des copies de site compare chaque copie à la vue qu'elle masque
- Un test vérifie que ce qu'importe l'outillage est bien déclaré
- Migration Odoo automatisée : l'outil mène toute l'exécution — réparer, rejouer, un déroulement automatique qui prend le défaut au bout de cinq secondes, et un compte à rebours qui nomme la réponse qu'il va prendre
- Écran d'état de migration : « t » montre où en est une exécution, avec les commandes en couleur, la durée écoulée, le journal du serveur lu pour vous, et un fichier de journal par étape sur disque
- Qualité de migration : ce qu'une exécution a gagné et perdu étape par étape, les fichiers manquants nommés, les refontes propres à Odoo distinguées des vraies pertes, et les changements déclarés par OpenUpgrade superposés aux réels
- Réparations de migration : le SCSS personnalisé que le palier suivant casse, prévu puis corrigé ; les thèmes désinstallés avant le premier palier ; la visibilité DMS rétablie ; les vues dont le type stocké contredit leur parent ; et les balises <tree> qu'Odoo 18 a renommées en <list>
- Tests de fumée après une migration : chaque URL publique demandée, /my et chaque application ouverte sous l'utilisateur de test de neutralisation, les vues derrière une URL en échec nommées, et le nettoyage de base OCA passé d'abord
- Vérification du filestore : si les fichiers joints sont bien arrivés, si l'enregistrement existe encore, et les nettoyages proposés sur place
- Analyse : les modules qui manquent à une base par rapport au paquet par défaut, avec une offre d'installer ceux qui sont prêts, et les fichiers joints réellement irrécupérables
- Debian sur s390x par debian-installer, aucune image cloud n'étant publiée pour cette architecture
- Une VM de développement mobile : PyCharm, Android Studio, extensions GNOME, un émulateur Android et un tunnel adb pour scrcpy, l'application mobile étant compilée et testée dedans
- Forgejo, une forge git installable depuis le menu de déploiement
- Matériel réglé par VM : le GPU de l'hôte, le mode CPU, les écrans et le réseau
- virt-viewer ouvre l'écran d'une VM depuis le menu
- Le tableau de bord d'installation affiche la RAM de l'hôte, la RAM utilisée et l'uptime d'une VM, et depuis combien de temps un journal est muet
- Une VM accueille sa connexion SSH avec les commandes propres à sa distribution
- Proxmox VE comme cible de déploiement : déployer une VM sur un hôte Proxmox distant depuis un écran qui récapitule dans le terminal avant de créer, crée le pont manquant, suit la VM et change son état, montre sa colonne Odoo et le lien web, et la supprime depuis l'hôte. Toute VM distante vient désormais avec son guide de connexion, qui manquait depuis le début
- Des réparations pour ce qu'un palier Odoo laisse derrière : les copies de site qui ne savent plus se rendre — prédites AVANT le palier plutôt que découvertes en 500 après — les index qu'Odoo 17 crée en double, et les réglages qu'aucun événement ne remet
- Des analyses qui lisent une base plutôt que de la compter : qui dépend de qui, à l'écran ; ce qui est installé, en cours et appliqué ; l'état d'une instance lu pour l'usage qu'on en fait ; et l'auscultation d'une base qui n'est pas ici
- L'anonymisation d'une copie sans IA : une copie de production sert à reproduire un défaut, les identifiants restent donc cohérents entre les tables une fois les noms remplacés
- Les statistiques de chaque VM : écriture, RAM, disque
- Le choix de la base au démarrage, sans jamais bloquer sur ce choix
- Le redémarrage fait partie de l'installation de Proxmox VE : install_proxmox.sh pose le noyau puis s'arrête, à raison, car lancé par ssh un reboot couperait sa session et ferait passer l'installation pour un échec. Le redémarrage revient à l'enveloppe de lancement, qui tourne sur NOTRE machine et survit à celle de la VM — installation, reboot, attente que « uname -r » porte le noyau Proxmox, puis vérification. Le ✅ ne s'écrit qu'après, et veut donc dire « hyperviseur utilisable »

## Modifié

- Le menu RTK affiche une icône devant chacune de ses six entrées, dernier menu dont les lignes ne se distinguaient que par leur numéro ; les glyphes sont pris parmi ceux que le fichier emploie déjà plutôt que choisis pour eux-mêmes, un caractère récent s'affichant en tofu sur un terminal dont la police l'ignore
- Le nom d'une VM bâtie sur une publication continue perd le segment de version : « latest » ne distingue aucune VM d'une autre. Une version nommée qui coexiste avec d'autres au catalogue y reste
- Chaque entrée de menu porte une icône, dix menus étant restés nus, et l'espacement suit la largeur RENDUE lue dans Unicode plutôt que devinée — deux espaces derrière un emoji d'une colonne, une derrière un large. La section Gérer de QEMU, devenue trop longue à parcourir, est scindée en Gérer, Accès à la VM et Dépannage
- L'indexation nomme les fichiers, jamais `git add -A`. Le ratissage indexe tout ce qui n'est pas suivi, et le dépôt garde deux répertoires non suivis EXPRÈS : `private/`, seul endroit autorisé à porter une donnée de client, et `tasks/`, où la convention envoie l'enquête précisément parce qu'il n'est pas versionné. Il emporte aussi ce qui est en cours ailleurs dans le checkout, sous un sujet qui ne le couvre pas ; `git add -p` indexe les hunks quand un fichier porte deux sujets
- Une invite à compte à rebours laisse 15 secondes pour décider, là où cinq ne suffisaient pas à LIRE la question : le compte à rebours n'existe pas pour aller vite mais pour qu'une exécution puisse être laissée sans surveillance, et trop court il fait l'inverse — la réponse vient par réflexe, ou un défaut que personne n'a lu s'applique. Une base restaurée porte le nom du fichier de sauvegarde, qui en porte déjà un parlant, plutôt que « test », sous lequel des migrations successives finissaient toutes sur un même nom. Le nom est assaini, puisqu'il finit dans un createdb, et borné à 41 caractères : le pilote ajoute « _neutralize_upgrade_18 » et PostgreSQL tronque à 63, ce qui ferait finir deux paliers sur le même nom. Un téléchargement distant garde celui que le serveur a donné
- todo.py éclaté en neuf fichiers, un par sujet, avec un socle commun par formulaire. Il portait 9 500 lignes de plus qu'un fichier ne devrait et tous les sujets y passaient ; les formulaires de déploiement répétaient la même mécanique de champs et de validation, si bien qu'une correction dans l'un ne gagnait jamais les autres. Aucun changement de comportement
- La branche, le profil et le type se choisissent par VM. Ils étaient globaux, ce qui obligeait à tout basculer pour déployer une seule machine autrement
- Un socle commun décrit le système invité, là où chaque formulaire le redécrivait
- L'installation prend en charge Fedora, Debian, Ubuntu et Arch Linux
- La synchronisation des dépôts et l'installation poetry tournent en
  parallèle, jusqu'à 50 % plus rapide sur une connexion lente
- Les modules extra CybroOdoo deviennent optionnels, suivis par version d'Odoo
- Node.js 22, exigé par Capacitor 8 pour l'application mobile
- Poetry et repo sont silencieux par défaut ; EL_VERBOSE rétablit la sortie
- Une VM hérite du fuseau horaire de l'hôte qui la crée
- Le premier démarrage n'attend plus snapd, la génération de locales ni l'agent
- apt prend le miroir joignable le plus rapide avant le dépôt officiel
- Selenium : téléchargement via un hub réseau, SVG vers PNG, détection
  d'erreurs, clics multiples et pilotes à jour
- Dépendance Odoo 18 : flanker
- Année de copyright portée à 2026
- Miroirs pacman canadiens placés en tête sur Arch, le miroir « géographique » officiel mesurant quatre fois plus lent depuis Montréal
- Une dépendance Poetry peut être déclinée par architecture : factur-x est épinglé en 3.x sur s390x, où saxonche ne publie pas de roue, et PyMuPDF y est écarté
- Entrée cible la version d'Odoo la plus élevée supportée, le défaut étant calculé depuis le menu

## Corrigé

- Un déploiement dit POURQUOI il faut un mot de passe avant que sudo ne le demande, et sur quel constat. sudo ne dit jamais ce qu'il sert à faire : l'invite tombe entre deux lignes de journal, et l'on tape un mot de passe sans savoir s'il porte sur libvirt, sur un paquet ou sur un fichier — d'autant qu'appartenir au groupe `libvirt` a tout l'air de suffire. Il ne suffit pas, et libvirt n'y est pour rien : le disque et le seed cloud-init s'écrivent dans le pool par défaut de libvirt, un répertoire de root où le groupe ne donne aucun droit d'écriture. La raison est donc CONSTATÉE et non affirmée — l'écriture se teste, une ACL pouvant l'accorder là où « drwxr-xr-x root root » semble la refuser —, puis nommée avec le répertoire, son propriétaire et son mode, à côté de ce que le groupe couvre vraiment : la socket qemu:///system, sondée en essayant. Dit une fois par exécution, avant la première commande privilégiée, et en dernière ligne du récapitulatif final, qui est l'écran juste avant l'invite. Root ne s'entend rien annoncer, aucune invite ne lui étant due ; un virsh absent se lit comme absent, et non comme un groupe en défaut
- Un réseau libvirt ne compte plus comme sa propre collision. Un réseau démarré porte et route son /24 sur son pont, et ce pont était lu comme « l'hôte occupe déjà ceci » : le verdict était donc « collision » sur toute machine où le réseau tournait, quel que soit le sous-réseau qu'il servait. `--setup-host` — et tout déploiement, qui passe par la même vérification — abattait alors le réseau et le déplaçait sur un /24 libre là où rien n'entrait en conflit, laissant les VM qui y étaient attachées sans passerelle et le tap détaché. Le pont du réseau examiné est désormais écarté de ce que l'hôte occupe, les adresses étant lues une interface par ligne pour que chacune se rattache à la sienne ; un nom de pont illisible n'écarte rien, le silence pesant du côté prudent. Le XML remis à « net-define » passe par un vrai fichier temporaire, imprévisible et retiré même quand virsh échoue, là où un nom composé de celui du réseau était un chemin devinable dans un répertoire où tout le monde écrit
- `--setup-host` ne laisse plus derrière lui une machine qui perd son réseau au démarrage suivant. Le réseau « default » de libvirt sert 192.168.122.0/24, et toute VM déployée par ce dépôt VIT dans ce réseau : son pont y prendrait l'adresse .1, celle de sa propre passerelle. virsh refuse ce démarrage — mais seulement tant que la route est là, et au démarrage libvirtd monte ses réseaux AVANT que le bail DHCP de l'hôte n'arrive : plus rien ne signale la collision, virbr0 prend l'adresse de la passerelle, et l'hôte n'a plus de réseau. L'autostart était armé même quand le démarrage venait d'échouer, et le message invitait alors à redémarrer. Le réseau est désormais DÉPLACÉ sur un /24 libre par redéfinition — laquelle ne demande ni pont ni module du noyau, donc elle passe là où le démarrage ne passe pas — en gardant son UUID, le nom de son pont et son adresse MAC, si bien que les domaines qui le nomment le retrouvent ; l'autostart ne s'arme que là où aucune collision ne reste, et se RETIRE là où il en reste une. Un réseau trouvé actif sur une route de l'hôte est abattu d'abord : c'est la machine déjà cassée, et c'est ce qui lui rend son accès au réseau, avant même qu'il y ait de quoi télécharger un correctif. Un seul redémarrage suffit toujours quand le seul obstacle est un noyau remplacé depuis le démarrage
- L'état d'un réseau libvirt est lu en anglais. virsh TRADUIT ses étiquettes : sous une locale française, « net-info » répond « Actif : non », où un motif sur « Active: yes » ne trouve jamais rien — tout réseau se lisait donc éteint, « --setup-host » déclarait l'hôte pas prêt quel que soit son état, et son conseil était de redémarrer pour rien. Toute sortie de virsh que l'on analyse passe maintenant par un appel unique qui force « LC_ALL=C », le même geste, pour la même raison, que l'écran de gestion QEMU
- L'installateur de starship ne fait plus avaler une page 404 à un shell. L'URL amont pointait sur un chemin qui n'existe pas ; le serveur y répond par une page HTML de 34 ko, que `curl -sS` écrit tout de même sur sa sortie en rendant 0, si bien que `sh` s'arrêtait sur `Syntax error` à sa deuxième ligne — un diagnostic qui ne dit ni l'URL fautive ni que rien n'a été posé. L'URL est corrigée, et `-f` fait taire curl et rendre 22 sur toute réponse d'erreur, comme le faisaient déjà les quatre autres installateurs amont du fichier
- Une question posée par une commande du menu se voit avant qu'on y réponde. La sortie était lue ligne par ligne, donc une invite sans saut de ligne restait retenue jusqu'à la ligne suivante et arrivait à l'écran APRÈS la réponse : tout « [o/N] » se répondait à l'aveugle. La lecture se fait désormais par blocs, le reliquat est montré aussitôt, et un décodeur incrémental protège les accents coupés entre deux lectures
- Un dépôt fautif n'emporte plus tout un lot de réécriture de remotes. Un répertoire vidé à la main passe le test du répertoire puis fait lever l'ouverture du dépôt — clone interrompu, `.git` effacé, deux états courants sur un checkout de développement — ce qui abandonnait tous les dépôts restants d'un lot de plus de cent. Un tel dépôt est ignoré, les écarts sont listés à la FIN plutôt qu'affichés au fil de l'eau où la trace les noie, et la sortie reste nulle
- Le hook commit-msg trouve sa bibliothèque sans masquer GitPython. Mettre `script/` en tête de `sys.path` faisait résoudre `import git` vers le paquet `script/git/` du dépôt plutôt que vers GitPython, pour tout module importé ENSUITE dans le même processus ; la racine du dépôt faisait de même au paquet standard `test`. Les deux passent en queue, si bien que les paquets installés gardent la priorité — `unittest discover -p 'test_git*.py'` passe de 49 tests et une erreur d'import à 84 verts
- Un checkout sans `.repo` garde son dépôt racine. Deux retours anticipés sautaient par-dessus le traitement de la racine, si bien qu'un manifeste absent rendait une liste vide alors que la racine était demandée : le script qui réécrit les remotes ne trouvait rien à faire et l'annonçait comme un succès. L'ajout de la racine et le tri passent par un point de sortie unique, et une origine absente vaut l'URL par défaut plutôt qu'une exception
- Le coffre KeePassXC s'ouvre sur une machine sans tkinter, c'est-à-dire sur tout serveur. Les deux imports partageaient un seul `try`, si bien que l'absence de tkinter mettait aussi PyKeePass à None : le coffre restait inouvrable même avec chemin et mot de passe configurés, alors que le journal annonçait « pykeepass is not installed » et que pykeepass 4.2 était là. tkinter ne sert qu'au sélecteur de fichier, quand aucun chemin n'est configuré. L'invite nomme aussi le coffre avant d'en demander le mot de passe, et non après
- Le menu QEMU passe par le groupe « libvirt » plutôt que par sudo, qui n'ajoutait aucun droit et réclamait un mot de passe à chaque entrée ; l'appartenance se tranche en ESSAYANT, jamais en lisant /etc/group. L'URI libvirt est nommée explicitement : sans « --connect », un virsh non root vise « qemu:///session », un hyperviseur SÉPARÉ où aucune VM du système n'existe, et « list --all » y rend une liste vide sans erreur — l'URI par défaut de root masquait l'omission
- Les outils système lancés depuis le menu n'héritent plus du venv en tête de leur PATH. Un outil écrit en Python et amorcé par « env python3 » démarrait dans un interpréteur privé des modules de la distribution et sortait sur « No module named 'gi' »
- Accepter d'installer les paquets QEMU ne redémarre plus l'hôte sans demander : « --assume-yes » couvrait le gestionnaire de paquets, et la commande y ajoutait « --reboot-if-needed » en silence. Une seule constante servait l'invité jetable et le poste de travail
- Trois écrans qui tombaient : les statistiques, où « datetime.datetime » n'existe pas puisque c'est la CLASSE qui est importée et où l'erreur emportait TODO entier ; une VM échouée dont la sortie montrait quatre lignes d'épilogue au lieu du message de l'outil ; et une clé i18n dupliquée qui écrasait un libellé du menu principal, la dernière définition gagnant dans un littéral de dict Python sans erreur ni avertissement
- Une réduction mesure la place libre AVANT de proposer la sauvegarde, qui double la place occupée et avait OUI pour défaut : sur un disque presque plein, une réponse vide lançait une copie qui s'arrête à mi-course et laisse un « .bak » tronqué
- « odoo_bin.sh db --drop » échouait par AccessDenied à chaque palier de migration, et le clone butait ensuite sur « database already exists » : db_restore.py lit le config.conf du dépôt, y voit admin_passwd = admin et n'envoie donc aucun mot de passe maître, quand odoo_bin.sh ne passait pas de « -c », si bien qu'Odoo lisait ~/.odoorc et son mot de passe haché. ODOO_RC ferme cette couture en un point plutôt qu'à vingt sites d'appel, les versions 12 à 18 le lisant après « -c » et avant ~/.odoorc, donc un choix explicite l'emporte toujours
- La vue SQL account.root que crée Odoo 17 est retirée avant le chargement en 18, où le modèle porte _auto = False et _table_query = '0', si bien que son nom n'entre plus dans aucune requête et que le contrôle des tables manquantes l'ignore. La vue n'est pas seulement morte mais FAUSSE, bâtie sur la colonne code que l'ORM 18 n'écrit plus, et elle est l'unique épingle des deux colonnes héritées où database_cleanup échoue — aucun DROP COLUMN, OpenUpgrade les lisant encore ensuite
- La réparation de migration créait des listes de prix qui n'avaient pas lieu d'être, de deux façons. Elle interrogeait `env.user.has_group()`, qui répond oui dès que l'exécutant est membre du groupe — et la migration l'y ajoute en cours de route —, là où la case des réglages lit tout autre chose : ce que `base.group_user` IMPLIQUE. Décider sur l'exécutant créait une liste de prix dans une base dont la fonctionnalité est éteinte, et Odoo prévenait alors à chaque ouverture des réglages qu'il allait l'archiver. Et une liste de prix partagée entre sociétés, au `company_id` vide, ne comptait pas comme appartenant à la société : la réparation voyait une société sans liste et fabriquait un doublon vide à côté de l'existante, sur une base qui n'avait pourtant rien perdu. Les deux lisent désormais l'implication du groupe et le détecteur `pricelist_missing` du même outil, qui distingue déjà les deux cas ; le contrôle « restant de migration » posait la même mauvaise question et a été corrigé avec elles
- La liste noire de l'anonymisation passait son SQL à psql en UN seul argument, et Linux plafonne un argument à 131 072 octets : le mode qui couvre le plus de tables était justement celui qui cassait, sur « OSError: [Errno 7] Argument list too long ». Le SQL passe désormais par un fichier avec `-f`, qui garde le `--single-transaction` que l'entrée standard aurait perdu en silence. Les colonnes texte à longueur déclarée sont tronquées par `left(…, n)`, l'identifiant en TÊTE pour qu'une colonne unique le reste, et tous les identifiants sont cités — Odoo laisse nommer un champ user ou order. Écarter toute colonne sous contrainte CHECK laissait le nom du partenaire intact : sur du texte, seules les contraintes de FORME sont hors de portée, et un UPDATE qui échoue n'écrit rien
- L'anonymisation respecte ce qu'une valeur SIGNIFIE, là où le type SQL dit seulement ce qu'elle EST. Odoo déclare `parent_path` en `char` mais y range un chemin d'identifiants — 1/7/12/ — reparsé aussitôt par `int()` : un nom écrit là casse le premier chargement de page ; tout modèle `_parent_store` en porte un, et `account_payment_term.days_next_month` passe de même à `int()`. Les deux noms connus sont écartés, puis le contenu lui-même est sondé : une colonne dont chaque valeur est un chemin reste intacte, même dans un module maison, et les barres obliques sont exigées, si bien qu'une valeur tout en chiffres n'échappe pas à l'anonymisation en passant pour un identifiant. Les nombres étaient tirés uniformément sur 0 à 1000, ce qui est faux pour tout nombre borné par son usage — heures, pourcentages, taux : un `float` qui porte une heure de la journée, tiré hors de 0..23, fait lever « ValueError: hour must be in 0..23 » à l'affichage de la fiche, borne qui vit dans le Python d'Odoo là où aucune contrainte PostgreSQL ne la déclare. Le tirage respecte désormais la seule borne que les DONNÉES déclarent, leur propre étendue, min et max mesurés par table ; 0 à 1000 ne reste que pour une colonne vide ou impossible à sonder
- Le lanceur unitaire ne prenait que sept préfixes de noms, « le reste demandant une base de données », et exécutait 1131 tests là où les 3703 du répertoire passent avec PostgreSQL injoignable ; il balaie test/test_*.py. Deux formes rendent un fichier muet sans erreur — unittest.main() posé en plein milieu, qui sort avant même que la seconde moitié soit définie (quatre fichiers, 87 tests), et l'absence de bloc __main__, qui compte zéro (huit fichiers, 174 tests) — et une garde refuse désormais les deux, ainsi que tout retour à une liste de préfixes
- Le vérificateur du transfert mobile n'acceptait que la disposition en packs, quand une compilation réelle livre un tar.gz par dépôt. Il échouait sur `<slug> : index.json absent` et arrêtait `compile_and_run.sh` avant l'APK — depuis le 2026-08-20, pour quiconque est sur le main mobile actuel. Il accepte désormais les deux dispositions, et prouve la présence de CHAQUE fichier promis plutôt qu'un échantillon de vingt : traverser les 139 archives coûte 6 s, et 124 350 fichiers sont comptés
- Le test du bundle gardait la limite d'entrées du ZIP en exigeant un champ `chunk` sur chaque fichier, c'est-à-dire la disposition en packs plutôt que la limite elle-même. Il compte maintenant les entrées que portera l'APK — 278 pour un plafond de 65 535 — si bien que les deux dispositions passent et qu'un retour au fichier-par-source échoue toujours
- La migration des paliers 13 à 18 tenait sur des suppositions : une ancre de page encodée en pourcent que l'analyseur ne lisait pas, web_responsive qui ne survit pas au passage en 18, un OpenUpgrade en échec qui passait pour fait, un clone rebâti qui gardait la préparation de l'ancien, et un module fautif qui emportait tout le lot de désinstallation
- Proxmox visait la mauvaise machine : l'installation partait sur l'hôte plutôt que sur la VM, le disque annoncé était celui de l'hôte, et quatre écrans parlaient d'une machine locale alors qu'ils pilotaient une machine distante. Le rebond est désormais le seul chemin vers une VM — viser directement ne marchait que tant que la VM avait une adresse routable. Six autres défauts sont venus d'un audit, pas de l'usage
- Un seul nom par entrée `~/.ssh/config`, et l'ancienne s'en va avec la convention qui l'a remplacée
- Le suivi ne met plus une VM à la poubelle avant d'en être sûr, et effacer depuis un suivi rouvert vérifie d'abord l'identité de la VM
- sshfs annonçait un montage qui n'avait pas eu lieu
- Odoo 15 déclare xlsxwriter, dont report_xlsx a toujours eu besoin
- La sonde du mot de passe maître de db_restore ne validait rien
- Une analyse cherchait l'identifiant externe de la liste de prix plutôt que la liste, et signalait des champs qui n'avaient jamais porté de donnée
- Le pont NAT s'écrivait avant de savoir si le NAT existe. Six lignes d'iptables et « code de retour 1 » arrivaient après que la strophe soit déjà posée dans /etc/network/interfaces, et rien dans ce bruit ne disait qu'il fallait redémarrer : l'hôte tournait le noyau cloud de Debian, dépouillé de netfilter. C'est notre propre install_proxmox.sh qui produit cet état, donc une Proxmox imbriquée fraîchement installée y est TOUJOURS — le garde va désormais là où la conséquence est, et non à la confirmation de l'hôte
- Une installation en échec n'est plus rapportée comme réussie : le code de
  sortie remonte toute la chaîne
- --with_extra s'applique désormais à un environnement déjà installé
- Le chemin d'addons ne pointe plus vers un dépôt que le manifeste Odoo 18 ne
  clone jamais
- repo init reçoit un nom de branche, une installation neuve n'échoue plus
- Le suivi d'installation suit une VM dont le bail DHCP change
- Installation sur Debian 13, Fedora et Ubuntu 26.04 : verrou apt, wkhtmltopdf,
  SELinux et le compilateur C manquant
- La chaîne de compilation s390x, sur Debian comme sur EL9, EL10, Fedora et openSUSE : compilateurs et en-têtes manquants, Rust pour cryptography et bcrypt, qpdf pour pikepdf, libclang pour pymupdf, des noms de paquets qui changent d'une version à l'autre, et un lot en échec sur un seul nom inconnu sans jamais le nommer
- L'installation d'un bureau graphique figeait trente minutes sur un paquet snap qui ne joignait pas le magasin
- Le compilateur était tué faute de mémoire en bâtissant CPython sur une petite VM s390x
- Le README ne listait ni Fedora, ni openSUSE, ni Linux Mint, ni Debian 13, toutes supportées
- Les outils de migration COW et la mise à niveau de la base parlent la langue du système
- Les outils d'analyse et de migration sont exécutables
- L'installateur forgejo ne réaffiche plus le mot de passe administrateur qu'il vient de poser
- La connexion Selenium renvoyait le défaut de configuration au lieu des identifiants reçus, lors de la reprise après une modale
- db_restore redemande le mot de passe maître au lieu de mourir sur une faute de frappe
- pyproj exige le binaire proj, pas seulement ses en-têtes, et PROJ est bâti là où la distribution est en retard
- run.sh est lancé par bash, contre les échecs 203/EXEC de systemd
- pykcs11 se compile avec SWIG 4.3 et au-delà
- os-release remplace lsb_release, et une collision d'IP se voit mieux

## Retiré

- Le contrôle de résidus qui jugeait cassée une langue dont la ligne res_lang porte active à NULL — listée nulle part, plus réactivable. Faux dans la source 18 : un domaine ('active','=',False) compile en (IS NULL OR = FALSE), l'action du menu Langues porte active_test: False, le tri passe par COALESCE(active, FALSE), et la lecture rend bool(value). C'est Odoo lui-même qui écrit ce NULL, active étant un booléen sans défaut et res.lang.csv n'ayant pas cette colonne, soit un NULL par langue ajoutée au catalogue — « zéro avant, non nul après » ne suffit donc pas à déclarer un résidu. Un test refuse désormais une clé de verdict que plus rien ne définit
- Le support d'Ubuntu 20.04 et 22.04, sur toutes les architectures : pikepdf réclame qpdf 12.2, dont la compilation exige C++20, quand focal livre GCC 9 et ne publie pas de `g++-10` pour s390x

## Sécurité

- Les mots de passe et jetons sont caviardés avant l'affichage ou la journalisation d'une commande
- Le mot de passe maître d'Odoo ne voyage plus sur la ligne de commande : MASTER_PWD le porte, et /proc/<pid>/environ n'est lisible que par son propriétaire là où /proc/<pid>/cmdline l'est par tout utilisateur de la machine (exige le commit correspondant dans le fork odoo)
- Le mot de passe KeePass parvient à la connexion Selenium de la même façon : la commande porte le NOM d'une variable d'environnement, jamais la valeur
- Ce qu'une commande AFFICHE est caviardé comme la commande elle-même : un outil qui réaffiche ses propres arguments ne remet plus le secret dans le terminal ni dans le fichier de journal


## [1.7.0] - 2026-03-11

**Notes de migration**

Recréer l'environnement virtuel, utiliser le guide d'installation depuis l'outil `make`.

## Ajouté

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

## Modifié

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

## Corrigé

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


## [1.6.0] - 2025-04-25

## Ajouté

- Support de plusieurs versions Odoo (12.0, 14.0, 16.0) dans le même espace de travail
    - Cela aidera pour la migration des modules
- Script Selenium pour augmenter l'interface client logiciel libre et automatiser certaines actions.
    - Enregistrement vidéo
    - Support du défilement et de la génération de mots
- FAQ sur comment tuer git-daemon
- Support d'Arch Linux, Ubuntu 23.10 à 25.04
- AJOUT du dépôt JayVora-SerpentCS_SerpentCS_Contributions
- AJOUT du dépôt CybroOdoo_CybroAddons

## Modifié

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

### Corrigé

- NPM installé localement et non globalement
- Amélioration de l'efficacité du générateur de code Python
- Le générateur de configuration supporte les espaces dans le répertoire ERPLibre
- Script de mise à jour de Poetry pour supporter les URL avec @
- Installation OSX et Ubuntu récent
- Intégration du script Cloudflare


## [1.5.0] - 2023-07-07

**Notes de migration**

Recréer l'environnement virtuel


```bash
rm -rf ~/.poetry
rm -rf ~/.pyenv

rm ./get-poetry.py
rm -rf ./.venv

make install
```


Faire une sauvegarde de votre base de données et mettre à jour tous les modules :


```bash
./run.sh --no-http --stop-after-init -d DATABASE -u all
```

## Ajouté

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

## Modifié

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

### Corrigé

- Script d'installation Debian 11
- Résultats de tests
- Installation OSX (support non terminé)
- La mise à jour de Poetry supporte '~='

### Supprimé

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


## [1.4.0] - 2022-10-05

**Note de migration**

- Mettre à jour les modules `website`,`website_form_builder`.
- Pour le développement, exécuter `poetry cache clear --all pypi`

### Ajouté

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

### Modifié

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

### Corrigé

- Poetry supporte les dépendances Python insensibles à la casse
- Le nouveau projet du code generator supporte les chemins relatifs et vérifie les chemins dupliqués
- Couleur d'arrière-plan de l'en-tête de tableau du thème web Muk et survol pour Many2many
- Le script docker-compose utilise des noms en minuscules
- website_form_builder support HTML et option pour aligner le bouton d'envoi
- Cherry-pick Odoo de 2 commits correctif bus
- Correction mineure de couleur CSS dans le module hr_theme du dépôt CybroOdoo_OpenHRMS
- Faute de frappe dans la tâche de projet lors de la saisie du temps

### Supprimé

- Paquet de module erplibre de ERPLibre_erplibre_addons, utiliser à la place la création d'image, voir le Makefile


## [1.3.0] - 2022-01-25

**Note de migration**

Avec la nouvelle version de poetry, un bogue survient lors de la mise à jour. La solution est de supprimer le répertoire pour le laisser
se recréer. `rm -rf ~/.poetry`

### Ajouté

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

### Modifié

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

### Corrigé

- Rétrogradation Werkzeug==0.11.15, seule cette version est supportée par Odoo 12.0. Cela corrige certaines requêtes HTTP derrière un proxy.


## [1.2.1] - 2021-09-28

### Ajouté

- doc/migration.md

### Modifié

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

#### Code generator

- Amélioration du code de génération db_servers
- Amélioration du menu UI de l'assistant de génération

### Corrigé

- Élément de menu vue mobile dans l'interface Web de muk_web_theme


## [1.2.0] - 2021-07-21

**Note de migration**

Parce que le dépôt d'addons a changé, le fichier de configuration doit être mis à jour.

- Lors de la mise à niveau vers la version 1.2.0 :
    - Depuis docker
        - Cloner le projet si vous avez seulement téléchargé docker-compose
            - `git init`
            - `git remote add origin https://github.com/erplibre/erplibre`
            - `git fetch`
            - `mv ./docker-compose.yml /tmp/temp_docker-compose.yml`
            - `git checkout master`
            - `mv /tmp/temp_docker-compose.yml ./docker-compose.yml`
        - Mettre à jour `./docker-compose.yml` selon les différences avec git.
        - Exécuter le script `make docker_exec_erplibre_gen_config`
        - Redémarrer le docker `make docker_restart_daemon`
    - Depuis une installation vanilla
        - Exécuter le script `make install_dev`
        - Redémarrer votre daemon
        - Régénérer le mot de passe maître manuellement

### Ajouté

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

#### Makefile

- Formatage du code
- Test du code generator
- Installation des addons
- Installation du système d'exploitation
- Restauration de base de données
- Exécution Docker

#### Code generator

- Code generator pour les modules Odoo, dépendant d'ERPLibre
- Support des cartes géospatiales
- Support i18n
- Script pour transformer Python et XML en script d'écriture de code Python pour se régénérer eux-mêmes

### Modifié

- Mise à jour des dépendances Python avec Poetry
- Formatage de tout le code Python avec black
- Module auto_backup avec clé d'hôte sftp
- Le module muk_website_branding utilise le branding ERPLibre
- Mise à jour de la documentation avec le support vscode, mise en page de document personnalisée, modèle d'email personnalisé et astuce pour utiliser les paramètres de partage
  de variables

#### Docker

- Utilisation de l'image buster python 3.7.7 pour supprimer pyenv
- Mise à jour de PostgreSQL pour supporter PostGIS
- Support du volume addons /ERPLibre/addons/addons

### Corrigé

- Installation Ubuntu
- Installation de Poetry
- Le géospatial avec PostGIS peut être installé


## [1.1.1] - 2020-12-11

### Ajouté

- Documentation développeur, test, migration et utilisateur
- Branding ERPLibre avec muk_branding
- Désinstallation de module depuis les paramètres Odoo
- Makefile pour générer la documentation ERPLibre (travail en cours)
- Support Docker du volume sur /etc/odoo
- Support Docker de la mise à jour de base de données

### Modifié

- Meilleure documentation sur l'utilisation d'ERPLibre et les versions
- Support de wkhtmltox_0.12.6-1

### Corrigé

- db_backup pour accepter la clé d'hôte publique sur sftp
- Dépendances Docker
- Gel de la version poetry 1.0.10


## [1.1.0] - 2020-09-30

### Ajouté

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

### Modifié

- Mise à jour vers Odoo Community 12.0 et tous les addons
- Renommage de venv en .venv
- Plus de documentation sur l'utilisation d'ERPLibre


## [1.0.1] - 2020-07-14

### Ajouté

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

### Corrigé

- Installation de production avec git_repo


## [1.0.0] - 2020-07-04

### Ajouté

- Environnement de développement, découverte et production avec documentation et scripts.
- Google git-repo pour supporter le dépôt d'addons au lieu d'utiliser les sous-modules Git.

### Supprimé

- Sous-modules Git


## [0.1.1] - 2020-04-28

### Ajouté

- Support du helpdesk fournisseur, assistant, employé et services
- Support de [SanteLibre.ca](https://santelibre.ca) avec MRP, site web, RH, commerce en ligne
- Module de don avec thermomètre pour le site web
- Script pour forker le projet et tous les dépôts en sous-module pour créer ERPLibre


## [0.1.0] - 2020-04-20

### Ajouté

- Déplacement du projet de https://github.com/mathbentech/InstallScript vers ERPLibre.
- Support d'Odoo Community 12.0 2019-11-19 94bcbc92e5e5a6fd3de7267e3c01f8c11fb045f4.

### Modifié

- Support de scrummer, projet, vente, site web, helpdesk et RH
- Support de Nginx et amélioration de l'installation

### Corrigé

- Support uniquement de python3.6 et python3.7, python3.8 cause des erreurs à l'exécution.


[Unreleased]: https://github.com/ERPLibre/ERPLibre/compare/v1.7.0...HEAD

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