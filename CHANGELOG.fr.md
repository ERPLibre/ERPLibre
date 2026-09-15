
# Journal des modifications

Tous les changements notables de ce projet seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com). Ce projet adhère
au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## Ajouté

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
- NixOS 25.11 parmi les systèmes déployables, à côté des huit autres. C'est le seul dont aucune distribution ne publie d'image cloud : l'image est rebâtie par un tiers, donc sa version est épinglée, sa somme sha256 vérifiée à chaque téléchargement, et son origine dite avant que rien ne soit créé. cloud-init n'y reçoit aucune configuration réseau — son moteur networkd prend la clé d'un bloc pour un NOM d'interface, là où netplan honore un `match:` — et le compte y est créé avec `/bin/sh`, sshd refusant un compte dont le shell n'existe pas
- ERPLibre installé sur NixOS, ses dépendances DÉCLARÉES dans `conf/nixos/erplibre.nix` puis appliquées par `nixos-rebuild`, là où les quatre autres familles les installent commande par commande. `services.envfs` répond à `/usr/bin/env` et `programs.nix-ld` donne aux roues manylinux le chargeur dynamique qu'elles réclament ; les en-têtes de ce qui n'a pas de roue sont liés au profil du système, et leurs bibliothèques vont aussi au chargeur, un module compilé sur la machine ne portant pas de RPATH. L'installation l'atteint depuis le menu comme toute autre distribution : l'amorçage pose git, make et python3 — absents de cette image — dans le profil de l'utilisateur pour la durée du clone, et « make install_os » les redéclare pour le système. Vérifié sur une VM : le verrou de 362 paquets s'installe et Odoo répond en HTTP
- Une option `nix + nixos-anywhere` sur les AUTRES distributions, l'inverse de choisir NixOS : elle laisse une VM ordinaire capable d'installer NixOS sur toute machine joignable en SSH. Nix est appelé par son chemin absolu, le PATH du shell distant étant figé avant que l'installateur ne pose le binaire, et les fonctions des flakes sont redonnées sur la ligne de commande, l'écriture de `nix.conf` réclamant un sudo qui peut manquer
- NixOS se déploie sur un hôte **Proxmox** comme sur QEMU/KVM, ce qui a demandé trois correctifs qu'aucune lecture de code n'aurait trouvés. Son image n'a pas de secteur d'amorçage BIOS : une VM créée en SeaBIOS se déclare « running » avec une console muette, donc le catalogue marque désormais les images qui exigent l'UEFI — un marqueur par distribution, Debian 13 démarrant en SeaBIOS sur ce même hôte. `--ciuser` et `--sshkeys` s'en remettent au compte par DÉFAUT de l'image, que NixOS nomme autrement : le cloud-config du dépôt part maintenant comme extrait pour toutes les distributions, avec son bloc `users:` explicite. Et le lecteur cloud-init passe sur le bus SCSI — une image bâtie pour virtio seul n'a pas de pilote ATA et ne voit jamais un lecteur IDE, si bien que cloud-init cherchait des sources réseau et que la VM arrivait sans aucun compte. Vérifié de bout en bout : NixOS rend `/bin/sh`, Debian 13 `/bin/bash`, sudo aux deux
- L'image tierce est vérifiée contre la somme que le dépôt épingle pour elle sur le chemin Proxmox aussi, où un `wget` nu suffisait. Un seul accesseur porte cette somme pour les deux chemins, et le contrôle vaut même pour une image déjà en cache — le cas visé est un fichier substitué ou tronqué entre deux déploiements, qu'un test de présence ne voit pas
- Une entrée du cache de téléchargement peut être retirée, par son URL. Une somme qui ne correspond pas n'invalidait rien : le magasin continuait de servir les mêmes octets, et retélécharger ne changeait rien puisque c'est lui qui répond. Aucune des deux purges ne l'atteint — `--purge` efface tout, et `--purge-older-than` saute ce qui est récent alors que chaque service remet cette date, si bien qu'un objet empoisonné qui sert ne vieillit jamais. `--oublie` est le symétrique de `--detient` : mêmes lignes en entrée, mêmes fonctions de clé, mêmes refus, et un objet présent qui résiste est dit refusé plutôt qu'oublié. Les deux échecs de somme le nomment désormais, avec l'URL exacte
- Le journal d'installation porte ce que l'hôte a décidé avant de lancer : l'autorité du cache de téléchargement posée ou refusée, l'exception, le miroir. Ces lignes se disaient sur une console qui défile, pendant que le fichier qu'on rouvre après un échec ne portait que le symptôme — sur un invité sans magasin de confiance, un certificat refusé, des centaines de dérivations à construire et six cents lignes d'erreurs, sans un mot sur la cause
- Une entrée du cache de téléchargement s'oublie depuis le menu, sous « Âge et nettoyage ». Le binaire savait déjà le faire ; le menu n'offrait que les deux purges en gros, dont aucune ne vise un objet — « effacer ce qui n'a plus servi » n'atteint jamais celui que le service rajeunit chaque fois qu'il le rend, et « tout effacer » coûte le cache entier pour un fichier. `--detient` passe d'abord et fait l'aperçu : même ligne, même clé, sans rien modifier

## Modifié

- `Assistant › [1]` n'envoie plus chaque question à une seule API distante sur un modèle figé : elle interroge le serveur configuré, et ne retombe sur le distant que lorsqu'aucun serveur local ne répond
- Le contrôle d'hygiène des commentaires lit le Go, et non les seuls `#` : `//` hors d'une chaîne, la chaîne brute entre accents graves, et les blocs `/* … */`
- Les index `by-hash` de Debian et d'Ubuntu sont servis du disque, leur nom étant l'empreinte de leur contenu ; `…/releases/latest/download/…` n'est plus figé sur la première version vue
- Un amont qui refuse ou ignore les connexions est retenu 20 s : une requête qui a une réponse gardée est servie aussitôt au lieu d'attendre son délai d'établissement, qui faisait l'essentiel du temps d'une installation hors ligne ; une requête sans rien en réserve tente toujours l'amont. Un miroir git saute son rafraîchissement tant que sa forge est injoignable
- Le pré-remplissage des miroirs tourne sous le compte du service du cache, jamais en root
- Le menu des tests longs demande avant de créer de vraies machines, et redemande, avec des mots à lui, avant que `--detruire` efface des machines avec leurs disques. La commande est montrée d'abord, c'est elle qui rend la question répondable ; un plan à blanc ou un rapport de performance ne crée rien et ne demande rien
- Chaque entrée du menu Proxmox VE porte une icône, la même image voulant dire la même action que dans les autres menus de l'outil

## Corrigé

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

## Retiré

- La dépendance `sshconf`, déclarée et installée partout et importée nulle part

## Sécurité

- Une clé d'API et un jeton Bearer sont caviardés eux aussi avant qu'une commande soit affichée, journalisée ou réimprimée : `OPENAI_API_KEY=` partait en clair, et un jeton d'en-tête échappait par construction, ne portant ni nom d'option ni nom de variable
- En suivant une redirection, le cache ne transmet plus les identifiants du client (Authorization, Cookie, Proxy-Authorization) à un autre hôte


## [1.8.0] - 2026-09-04

**Notes de migration**

Recréer l'environnement virtuel, l'interpréteur Python et l'installateur de
paquets se choisissant désormais. Utiliser le guide d'installation depuis
l'outil `make`. Ubuntu 20.04 et 22.04 ne sont plus supportés.

## Ajouté

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

## Modifié

- todo.py éclaté en neuf fichiers, un par sujet, avec un socle commun par formulaire
- Chaque entrée de menu porte une icône, les menus sont regroupés en sections, et une invite à compte à rebours laisse 15 secondes pour décider
- La branche, le profil, le type et le fuseau se choisissent par VM plutôt que globalement
- L'installation couvre Fedora, Debian, Ubuntu, Arch et openSUSE ; la synchronisation des dépôts et Poetry tournent en parallèle, silencieux sauf si EL_VERBOSE le demande
- Node.js 22 pour Capacitor 8, flanker pour Odoo 18, les extras CybroOdoo optionnels, et une dépendance Poetry déclinable par architecture
- Une VM démarre plus vite et prend le miroir joignable le plus rapide, les miroirs pacman canadiens passant en tête sur Arch
- L'indexation nomme les fichiers, jamais `git add -A`
- Entrée cible la version d'Odoo la plus élevée supportée, et un nom de VM perd le segment `latest`

## Corrigé

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

## Retiré

- Le support d'Ubuntu 20.04 et 22.04, sur toutes les architectures
- Le contrôle de résidus qui jugeait cassée une langue dont `active` est NULL

## Sécurité

- Les mots de passe et jetons sont caviardés avant l'affichage, la journalisation ou le réaffichage d'une commande
- Le mot de passe maître d'Odoo et celui de KeePass quittent la ligne de commande, une variable d'environnement les portant à la place


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