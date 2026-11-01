
# Journal des modifications

Tous les changements notables de ce projet seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com). Ce projet adhère
au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

## Ajouté

- Le programme du deck Stream Deck accepte des plugins venus de `$XDG_CONFIG_HOME/erplibre-home/deck-plugins/`, en plus des onze que livre le dépôt ; un plugin qui ne se charge pas est refusé avec sa raison au journal et les autres continuent
- `DECK_PLUGINS_OFF` dans `streamdeck.conf` et TODO › Stream Deck › Plugins on/off coupent des plugins du deck ; `erplibre_streamdeck --list-plugins` affiche chaque plugin et son état sans ouvrir le deck
- `DECK_SESSION_REFRESH_SEC` dans `streamdeck.conf` (0,5 à 60 secondes, 1 par défaut) règle la fréquence de rafraîchissement des pages de session ; TODO › Stream Deck › [13] le modifie
- Une passerelle cellulaire sur un modem USB, accessible depuis **Passerelle mobile** dans Odoo :
  elle relaie par la carte SIM les SMS qu'Odoo veut envoyer, rapporte les appels qui entrent, et
  évite au serveur d'avoir jamais à joindre l'appareil — c'est l'agent qui vient chercher son
  travail, donc une adresse dynamique et un NAT d'opérateur n'y changent rien. L'échange est
  authentifié par une signature HMAC dont la clé est lue dans l'environnement du processus Odoo,
  jamais en base : le code de ce module est publié sous AGPL-3, et une clé en fiche part dans
  chaque sauvegarde et chaque copie de la base
- Un appel entrant fait sonner un softphone de navigateur, et la voix circule entre le navigateur et
  la SIM dans les deux sens — WebRTC d'un côté, la carte son du modem de l'autre. Le softphone
  dispose d'une trentaine de secondes pour décrocher : au-delà, la boîte vocale de l'opérateur prend
  l'appel, et c'est cette course que règle le nombre de sonneries
- Un répondeur à soi, qui décroche avant la boîte de l'opérateur et garde ainsi un historique
  qu'aucune commande AT ne permettrait de récupérer : il joue une annonce, émet un bip, enregistre,
  coupe le silence de fin du fichier autant que de la durée annoncée, et téléverse le message dans
  Odoo, où il s'écoute dans la fiche au lieu de se télécharger
- La boîte vocale de l'opérateur se relève en l'appelant : une recette de touches DTMF, cadencée sur
  les silences, parcourt le serveur vocal. Elle part sur le drapeau de message de la SIM — un
  relèvement occupe la ligne, il n'a pas de raison de partir sans rien à prendre — ou sur un bouton
  des réglages. Le message est découpé de l'appel, et les secondes où la boîte annonce le numéro de
  l'appelant le sont aussi : cette annonce est la seule trace de qui a appelé, l'opérateur ne le
  transmettant sous aucune forme lisible
- Les deux services du modem tournent sous systemd, secrets dans un `EnvironmentFile` en 0600 et
  jamais en base. Le NIP de la messagerie fait exception à dessein : il vit dans un coffre qu'une
  personne seule peut ouvrir, on le remet donc au service en marche par une socket locale et il n'est
  gardé qu'en mémoire — perdu à chaque redémarrage, ce que le menu annonce, parce que l'écrire
  quelque part annulerait le coffre
- La démonstration de bout en bout existe en deux exemplaires, un par matériel qui porte la carte
  SIM : le téléphone Android depuis **TODO › Assistant**, le modem USB depuis l'entrée 9 du menu du
  modem. Chacune a son état, sa base, son port, sa fiche passerelle et sa clé HMAC, si bien que les
  deux Odoo tiennent côte à côte sur un même poste et que configurer la seconde ne défait plus la
  première. Une entrée passe de l'une à l'autre sans rien perdre, ce qui rend les deux boucles
  comparables d'une seule séance
- Les réglages de la passerelle se posent sur le téléphone par le câble au lieu de se taper : la
  démonstration arrête l'application, écrit l'URL du serveur, l'identifiant d'appareil et la clé
  partagée de 64 caractères dans ses préférences, et efface le dernier refus enregistré. Tout ce que
  le serveur avait posé — rythme d'interrogation, quota de segments, choix de journalisation — est
  conservé, et le fichier précédent est copié à côté de l'état avant tout remplacement. Il y faut un
  paquet débogable, le seul qu'Android ouvre à `run-as`. La chaîne s'en sert d'elle-même à l'étape
  qui relie le téléphone, et ne demande rien ; le pense-bête à recopier ne paraît que lorsque le
  câble ne peut pas le porter, avec le motif
- `mobile/compile_and_run.sh --lan-cleartext` construit l'APK de démonstration, le seul qu'Android
  laisse parler en HTTP clair à une adresse locale : sans lui, la passerelle SMS en Wi-Fi ne joint
  rien, le refus tombant avant que l'application voie la requête. La compilation mobile de **TODO**
  le demande et répond Non par défaut — il affaiblit une protection du système, il se demande donc
  à chaque compilation et ne s'hérite jamais — et une option mal tapée est refusée au lieu de
  produire l'APK ordinaire
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
- `erplibre_go_qemu_cache --recle` range à nouveau les objets d'un cache sous la clé courante, sans rien retélécharger, et fond les copies qu'un miroir portait sous plusieurs chemins. Les objets écrits sous l'ancienne règle de clé restent sur le disque mais deviennent INTROUVABLES, si bien que le service les redemande à l'amont et que la place qu'ils tiennent ne sert plus personne : sur un magasin de 12 764 objets, 5 419 étaient dans ce cas — 9,11 Gio — et la fusion des doublons a rendu environ 3,37 Gio. Le service doit être arrêté, le corps étant renommé avant son méta, et `--dry-run` ne fait que compter ce qui bougerait. Un statut seul n'est pas touché, sa clé portant l'hôte et non le chemin
- Le hook `pre-commit` lance `check_python_version.py` sur les fichiers indexés : il signale le source qui ne parse pas sous le Python de `conf/python-erplibre-version`, sans bloquer le commit, et dit quand aucun interpréteur de cette version n'était là pour vérifier. Ni black ni flake8 ne voient ce défaut — la cible de black borne ce qu'il écrit, jamais ce qu'il accepte
- `Déploiement › Local › [4]` ouvre un proxy SOCKS par SSH — `ssh -D`, port 1080 par défaut — pour que le navigateur atteigne, DEPUIS la machine distante, une interface qui n'écoute que sur sa boucle locale ou un hôte de son réseau. L'adresse vient de `~/.ssh/config` ou de la saisie ; un alias part tel quel à ssh, si bien que son `ProxyJump` s'applique encore et qu'une VM imbriquée reste joignable. Le réglage de Firefox s'affiche avant l'ouverture du tunnel, la commande ne rendant la main qu'au Ctrl+C
- `make format_test` formate `test/` et `long_test/`, qu'aucune cible ne couvrait : 75 fichiers sur 210 ne suivaient aucune norme, et seul un fichier signalé par un diff était touché
- `script/reverse_proxy/main.py` — un mandataire inverse de développement pour Odoo 18, sans nginx : une seule adresse envoie les pages au port web et `/websocket` au port du bus, les en-têtes `X-Forwarded-*` de `proxy_mode` n'étant posés que par le mandataire (`--trust-forwarded` prolonge plutôt une chaîne, derrière un autre mandataire). Seule la tête de la requête est lue : une WebSocket montée reste ouverte et une réponse gzip ou en morceaux passe octet pour octet. Il sert en HTTPS avec `--tls-cert`/`--tls-key`, écrit une ligne par requête (route, statut, durée ; `--quiet` la coupe), dit au démarrage quel port d'Odoo ne répond pas, et nomme ce port dans un 502. La tête d'une requête attend 30 s (408) et la connexion à Odoo 10 s (504), jamais une WebSocket ouverte. Écoute par défaut sur `127.0.0.1:8080`, `--listen 0.0.0.0` l'ouvre au réseau ; une requête par connexion, la production garde nginx
- `script/reverse_proxy/local_cert.py` émet une autorité locale, importée une fois dans le navigateur, et un certificat serveur qu'elle signe pour localhost, le nom d'hôte et ses adresses, sous `~/.erplibre/reverse_proxy_tls/` avec des clés en 0600 ; l'autorité est gardée quand le certificat est réémis
- `TODO › Execute › Network › Mandataire inverse Odoo` le lance avec les ports web et bus lus dans `config.conf`, demande cette machine seule ou tout le réseau et HTTP ou HTTPS, émet le certificat local au premier usage en HTTPS, et prévient quand `proxy_mode` est éteint ou que `workers` vaut 0 — sans worker, aucun port de bus n'écoute et `/websocket` échoue. `Network › Certificats TLS locaux` le réémet avec d'autres noms
- `TODO › Exécution › Docker / Podman` dit quel moteur répond, avec ou sans sudo, et nomme pourquoi l'un refuse — jusqu'à un compte ajouté au groupe `docker` après l'ouverture de sa session, ou un noyau mis à jour sans redémarrage. Un démon sans privilège est trouvé même quand `DOCKER_HOST` ne nomme pas sa socket. Le menu installe Docker — par le groupe `docker`, annoncé comme équivalent à root, ou sans privilège — ou Podman avec `script/install/install_container.sh`, pilote l'unité systemd du moteur et affiche son journal sur échec, et lance les six scripts de `script/docker/`, qui n'avaient que des cibles make
- Bâtir l'image d'une version d'Odoo, ou de toutes d'un seul balayage qui continue après une version en échec et finit sur ce qui est bâti et ce qui a échoué. Le balayage demande d'abord : une image de production pèse une dizaine de gigaoctets
- Nettoyer tout ce qui ne sert pas, un projet compose avec ses conteneurs, réseaux et volumes, ou des images choisies par leur rang. Une sélection fautive n'efface rien, et une image qu'un conteneur tient encore se décide avant tout effacement : la garder, effacer ses conteneurs puis l'image, ou forcer — offert seulement quand aucun conteneur en marche ne la tient, puisque forcer libère le nom et non la place
- `make test_unit_changed` (`--changed[=REF]`) ne lance que les fichiers de tests qu'un changement peut atteindre, depuis `HEAD` par défaut, fichiers non suivis compris : les dépendances se lisent dans le code — imports, et fichiers qu'un test nomme, comme le script shell qu'il lance. Un module que `TODO` charge atteint encore plus de la moitié de la suite, qui l'importe bel et bien
- `make test_unit_failed` (`--failed`) ne relance que les fichiers de tests en échec ou en délai au passage précédent ; un fichier sort de la liste en passant
- Le lanceur de tests unitaires offre `--slowest=N`, les N tests les plus lents ; `--junit=FICHIER`, un cas JUnit par test ; `--repeat=N`, qui nomme les fichiers dont l'issue varie d'un passage à l'autre ; et `--watch`, qui relance les tests qu'un fichier enregistré atteint. SIGTERM arrête les tests en cours comme Ctrl+C

- `TODO › Execute › Courriel › Ouvrir le client courriel (TUI)` — un client en trois volets dans le terminal, sur plusieurs comptes : lire, écrire, répondre, transférer, ranger, jeter, suivre, chercher, parcourir un dossier par pages et agir sur plusieurs messages à la fois. Il répond hors ligne depuis un cache local, et le corps d'un message arrive par un fil de travail qui ne le peint que si le curseur n'a pas bougé : l'écran n'attend jamais le réseau
- Un cache SQLite par compte, qu'un compte peut sceller : sujet, adresses, extrait et messages en attente sont chiffrés au repos, tandis que dates et drapeaux restent en clair — trier et compter ne doivent pas déchiffrer une ligne chacun. Les Message-ID sont gardés en empreintes salées, jamais lisibles, puisque ce sont eux qui relient une conversation. Le mode `ephemeral` tient le cache en mémoire le temps du processus, et celui qu'un processus tué laisse derrière lui est balayé au démarrage suivant
- Une passe de synchronisation est incrémentale — seuls les UID au-dessus du dernier connu, jamais les corps — et relit les drapeaux à chaque fois : un message lu ailleurs apparaît lu ici. Les comptes se synchronisent de front, comme les dossiers d'un même compte. Une lecture qui dépasse `mail_timeout_sec` (30 s) condamne la socket, donc chaque échange rouvre le lien une fois au lieu de le traîner ; un `UIDVALIDITY` changé purge le dossier plutôt que de fusionner sur des lignes qui désignent désormais autre chose
- Sur un serveur qui range par étiquettes, la passe écarte les vues qui ne redisent qu'un autre dossier — celles marquées `\Flagged` ou `\Important`, dont les messages sont tous aussi dans `\All` — pour qu'une boîte de 30 000 messages ne soit pas mise en cache trois fois. `\All` reste toujours synchronisé, archiver un message ne le laissant que là, et l'écart exige l'annonce `X-GM-EXT-1` : ailleurs `\All` désigne une archive ordinaire, aux messages distincts
- OAuth pour les fournisseurs qui ont fermé le mot de passe : un tel compte s'ajoute avec un jeton de rafraîchissement, et le client nomme ceux qui n'acceptent que cela au lieu de laisser la connexion échouer sur un message qui accuse le mot de passe. Aucun identifiant client n'est livré — il serait public dès le premier clone, et chaque fournisseur offre un chemin où la personne obtient le sien
- Des statistiques sur le seul cache, sans rien demander au serveur : volume par jour, semaine ou mois, correspondants les plus présents, part encore non lue, poids sur le disque. Presque tout se compte en SQL sur les colonnes restées en clair, donc un compte scellé n'est pas un compte aveugle ; les correspondants sont l'exception, descellés ligne par ligne en mémoire et annonçant leur progression
- Chercher dans le cache du dossier ouvert, du compte ou de tous les comptes, et poser la même question au serveur quand le cache ne sait pas y répondre. Un cache scellé ne porte pas d'index plein texte — c'est le scellement qui l'interdit — et la recherche compare alors les champs qu'elle peut encore lire
- Les installeurs posent gettext (gettext-tools sur SUSE) sur chaque système supporté, sans jamais bloquer : `msgfmt --check` attrape une traduction qui a perdu un `%s` avant qu'elle n'apparaisse sur une page, et `msgmerge` reporte les traductions sur un `.pot` régénéré
- `coverage` est dans les venvs d'Odoo 16, 17 et 18 : `ODOO_MODE_COVERAGE=true` fait tourner Odoo sous coverage au lieu d'échouer sur « command not found »
- `doc/S390x/` guide une installation sur IBM Z : l'ordre des étapes, les particularités de chaque système supporté, et ce qui manque à s390x ou s'y ajoute par rapport à amd64 — PyPI n'a presque aucun wheel s390x, pip compile donc, ce qui amène des paquets en plus, du swap, Rust et la compilation de qpdf et PROJ, et écarte wkhtmltopdf, PyMuPDF et factur-x 4
- Le suivi d'installation ajoute des VM aux installations en cours : la touche `e` ouvre le formulaire de déploiement habituel dans le même terminal, puis crée les VM pendant que le tableau continue de suivre, les ajoute à la session ouverte et ajoute leurs lignes ; le titre compte en rouge celles encore en création. Le mode hors ligne et les noms déjà suivis sont refusés
- Une fenêtre d'aide sur `h`, ou F1 et `?`, liste tous les raccourcis du suivi d'installation, que son pied de page tronque dans un terminal étroit
- Les versions d'une publication se gèlent dans les manifestes eux-mêmes : `make repo_freeze` écrit le commit de chaque projet cloné de la version d'Odoo active dans son fichier, `manifest/git_manifest_odoo<V>.xml`, `_dev` ou `git_manifest_extra_odoo<V>.xml`, dans `freeze-revision`, à côté de la branche que `revision` garde ; les fragments communs suivent leur branche. Un seul fichier porte les deux lectures, et le choix est un argument conservé nulle part : `make repo_configure_all FREEZE=1` installe ou reconfigure sur les commits, `make repo_configure_all` suit les branches, `make repo_unfreeze` retire l'attribut. L'installation de TODO demande le développement, sur les branches, ou la production, sur les commits gelés, avec repli sur le développement quand la version choisie n'a aucun gel. Un projet non cloné, qu'un autre fichier fusionné définit aussi, ou dont aucune branche distante ne contient le commit est écarté et listé, puisqu'une installation neuve ne pourrait pas aller chercher ce commit. `.repo/local_manifests/erplibre_manifest.xml`, réécrit à chaque reconfiguration, ne porte jamais `freeze-revision`
- Deux gels se comparent par `make repo_freeze_diff` ou TODO › Git repo › 14 : par défaut le gel committé contre le commit où se trouve chaque clone, sinon deux états au choix parmi une révision d'ERPLibre, `manifest/` sur le disque et les clones. Un tableau compact donne pour chaque projet changé les commits gagnés et perdus, les fichiers et les lignes ; le diffstat suit, entier quand il est court et borné au-delà de 60 fichiers, et les lignes se regroupent par type de fichier, module Odoo ou dossier. L'historique s'ouvre dans tig, et un commit absent du clone est listé, puis recherché en parallèle sur demande. Chaque commit est placé sur la branche que nomme le manifeste, avec les refs du clone qui le contiennent et les branches et tags d'ERPLibre qui le gèlent ; une matrice montre côte à côte les commits gelés de plusieurs branches d'ERPLibre
- Le gel peut aussi retenir le commit amont sur lequel repose un fork : `make repo_freeze UPSTREAM=1`, `--upstream`, ou une question de TODO à Non par défaut, écrit la base de fusion du commit gelé et de la branche amont dans `fork-upstream-freeze-revision`, à côté des attributs du fork. C'est la seule partie du gel qui passe par le réseau, et seul un amont DÉCLARÉ est interrogé, une URL devinée à partir du nom d'un remote pouvant viser un autre dépôt. Un clone superficiel s'approfondit, par doublements jusqu'à 1600 commits, jusqu'à ce qu'apparaisse une base derrière laquelle aucune frontière du clone ne peut en cacher une meilleure. Un fork sans base — amont non déclaré ou injoignable, pas de branche amont, aucune ou plusieurs bases de fusion — est listé avec son motif, et son commit gelé quand même. La base ne vaut que pour le commit à côté d'elle : un gel qui change ce commit sans calculer de base la retire, et `make repo_unfreeze` aussi. git-repo ne la voit jamais
- La passe à sec de la mise à niveau compte les commits amont depuis la base gelée, et signale un amont réécrit depuis ; la comparaison des gels montre `upstream <ancienne> -> <nouvelle> +N -M` pour un fork dont la base a changé, y compris sous un commit gelé qui n'a pas changé, et une base changée seule compte comme un gel non committé
- La mise à niveau s'applique sur une branche datée `<branche>_maj_<AAAAMMJJ>` par un rebase ordinaire, où git écarte nos commits que l'amont a déjà repris. Seulement quand l'amont a été réécrit depuis le gel, le commit gelé étant dans l'historique de HEAD, seuls les commits posés depuis la base gelée se rejouent, par `rebase --onto`, de sorte que l'ancien amont ne se rejoue pas avec les commits du fork. Un fork sans commit propre, en retard sur l'amont, avance en fast-forward. Un arbre de travail modifié, ou une branche du fork dont HEAD ne contient pas la pointe distante, est refusé avant toute écriture. Un rebase ou un fast-forward que git refuse en cours de route, son checkout interrompu sur un arbre à moitié écrit, remet le dépôt sur sa branche ou son commit de départ, sans les fichiers de l'amont laissés hors suivi ni la branche datée
- TODO › Execute › Git › Repo › Publier les forks mis à niveau pousse ces branches datées sur le fork, chacune montrée et confirmée, toujours avec `--force-with-lease` sur la pointe distante relevée à la passe : un distant qui a bougé depuis refuse la publication. Un rebase terminé hors du menu se relit en entrant dans la file, le rapport ou la publication. Une ancienne pointe, ou un commit gelé, qu'aucun tag ni aucune autre branche du remote du fork ne retient, lus par `git ls-remote` au moment de publier, reçoit d'abord un tag ou une branche, au nom proposé et modifiable, poussé AVANT le push forcé. Le menu propose ensuite de geler de nouveau, le manifeste portant encore les anciens commits
- TODO › Execute › Git › Repo › État des forks et de leurs amonts liste ensuite les forks qui portent à la fois un commit gelé et une base amont gelée, avec `<base>..<gel>` et le compte de nos commits entre les deux, lu dans le clone sans réseau ; `N` ouvre cette plage dans tig, ou `git log --oneline --graph` sans tig, et `a` les ouvre l'une après l'autre. Un fork non cloné, ou dont le clone n'a pas l'un des deux commits, affiche son motif, et rien n'est récupéré
- L'amont d'un fork déclaré vit dans son clone sous un remote qui porte le nom de `fork-upstream-remote`, à l'URL que donnent les manifestes, si bien que la mise à niveau lit `OCA/18.0` plutôt que `FETCH_HEAD` : la passe à sec pose ce remote quand il manque, avec `--no-tags` et une refspec limitée à la branche déclarée, récupère dans sa branche de suivi, et le rebase, le fast-forward et leur reflog la nomment. TODO › Execute › Git › Repo › Ajouter les remotes amont, l'entrée 3, ou `repo_upgrade.py --add-remotes`, le pose et le récupère sur chaque fork sans diagnostic. L'écriture https et l'écriture ssh d'un même dépôt comptent pour la même URL. Un remote de ce nom qui vise un autre dépôt n'est jamais touché : le rapport donne la commande `git remote set-url` et la passe à sec rend le fork non comparable. Un clone superficiel reçoit le remote sans fetch, marqué `skipFetchAll` pour que `git fetch --all` le laisse de côté, le rapport donnant la commande manuelle à la profondeur du manifeste, et les forks sans amont déclaré sont listés comme sautés, avec leur motif. Le gel ne compte pas les branches de suivi de ce remote comme la preuve que le fork porte un commit
- `script/git/repo_state.py` écrit l'état du code en JSON stable (`schema` 1), en lecture seule et sûr pour le compte d'un service Odoo : `snapshot` donne les versions d'ERPLibre et d'Odoo, le mode, et pour chaque dépôt son HEAD, son écart à ce que demande le manifeste (`conforme`, `en_avance`, `decale`, `absent`, `hors_manifeste`, `sale` avec `--dirty`, fichiers non suivis et non ignorés compris), son amont et ses modules avec la version de leur `__manifest__.py`, sous une empreinte qui ne change qu'avec l'état ; `between` liste les commits entre deux révisions, bornés, et avec `--paths` les modules dont un fichier diffère ; `cross-version` compare un dépôt au même chemin sous les autres arbres `odoo<V>/` : versions des modules, nos commits à porter appariés par `git patch-id` et par sujet depuis la base amont la plus récente, historique et diffstat des modules, bornés sur un dépôt aussi grand que le cœur d'Odoo
- Quand le `.git` d'un dépôt ne peut pas être suivi — un lien cassé vers `.repo/projects/`, ou une cible que le compte ne lit pas, comme des clones faits par root et lus par le compte d'Odoo dans un conteneur —, `script/git/repo_state.py` nomme cette cause au lieu de « not the root of a git repository », git ayant répondu en silence pour le checkout ERPLibre parent. `snapshot` et `cross-version` ajoutent alors une clé `permissions` : le compte, le propriétaire, le nombre de dépôts touchés et un `chmod -R go+rX` sur `.repo` ou la racine du checkout à lancer en root, avec le nom du conteneur sous Docker. L'empreinte ignore cette clé, un conseil sur l'environnement et non un état du code
- L'entrée `upstream` de chaque fork d'un `repo_state.py snapshot` porte son écart avec l'amont : `base`, le commit d'où partent nos commits — la base commune avec la branche de suivi amont, sinon la base amont gelée — et `base_source` ; `ahead`, nos commits au-dessus ; `tracking`, la branche de suivi amont du clone, et `behind`, les commits amont que HEAD n'a pas. L'instantané reste en lecture seule et sans réseau : `behind` compte ce qu'a rapporté le dernier fetch de l'amont. Une valeur que le clone ne permet pas de calculer reste nulle : sans branche de suivi, pas de `behind` ; sans base, `base_reason` dit pourquoi
- `script/git/repo_apply.py --apply --confirm <version> --expect <chemin>...` applique une passe de mise à niveau sans le menu, pour un appelant qui a déjà montré l'essai à sec : il refait le diagnostic et n'écrit rien quand les forks sans conflit prédit diffèrent de `--expect`, ou quand un fork épinglé par `--expect <chemin>=<sha amont>:<sha HEAD>` a bougé depuis l'essai à sec, laisse au menu les conflits prédits, abandonne le rebase d'un fork qui bute malgré tout et le remet sur son commit de départ, inscrit la passe sous `tasks/git_repo_upgrade/` et ne pousse jamais
- `make install_browser_test` installe le navigateur que cherchent les tests navigateur d'Odoo (tours, hoot), selon la distribution : `chromium` du système sur Debian, Linux Mint, Fedora, la famille RHEL, openSUSE et Arch, le `.deb` de Google Chrome sur Ubuntu, dont le `chromium-browser` est un snap qui cache à Odoo le port de débogage, Google Chrome sur macOS, et la déclaration à écrire sur NixOS. Un navigateur déjà dans le `PATH` n'est pas réinstallé, sauf un Chromium snap, `--dry-run` affiche les commandes, et le script dit aussi si le venv d'Odoo a `websocket-client`. Il reste hors de `make install_os`, que la production lance aussi. Sans navigateur, ces tests sautent et la passe reste verte
- L'amont de chaque fork est déclaré dans les manifestes — `fork-upstream-remote`, `fork-upstream-name` quand le nom du dépôt diffère, `fork-upstream` pour la branche — au lieu d'être deviné d'après le nom du remote, ce qui menait à un dépôt ou à une branche inexistants. TODO › Execute › Git › Repo › Mise à niveau — à sec prédit chaque rebase en mémoire et n'écrit rien : à rebaser, en conflit, ou absorbé quand l'amont a repris un module que le fork ajoutait. Un conflit pendant l'application laisse ce rebase en cours dans la file des conflits pendant que les autres forks avancent, et un écran en lecture seule montre pour chaque fork ses commits, ses conflits et ce qu'apporte l'amont
- TODO › Execute › Git › Repo › Tirer les dépôts, ou `script/git/repo_pull.py`, met à jour un checkout déployé depuis ses propres remotes, par branche ou par manifeste, en rebase, en avance rapide ou en fusion : un essai à sec d'abord, puis une passe épinglée sur lui. Chaque dépôt reçoit d'abord une branche de sauvegarde, un arbre modifié est mis de côté puis réappliqué, et un conflit remet ce dépôt en place pendant que la passe continue ; approfondir un clone superficiel, cloner de nouveaux dépôts et `poetry install` se demandent chacun d'abord
- La passe à sec et l'application de la mise à niveau proposent d'approfondir un fork dont le clone est superficiel, comme un cœur Odoo cloné avec `clone-depth`, qui n'a pas de base de fusion et reste sinon hors de la mise à niveau. À Non par défaut, `git fetch --unshallow` rapatrie toute la branche que suit le fork, puis sa branche amont, un clone après l'autre, et le diagnostic se refait ; ni branche locale ni arbre de travail ne bougent
- Le suivi d'installation relance les installations en échec : `r` la VM sélectionnée, `R` toutes celles en échec, après confirmation. La même commande repart, conservée VM par VM dans la session, et refuse de démarrer tant qu'un `make` tourne encore dans la VM, comme après une coupure SSH (code 255). L'ancien journal est gardé en `<journal>.N`. Une VM effacée, un nom repris par un autre domaine, une session hors ligne ou une coupure tenue par un autre déploiement sont refusés, comme les sessions lancées avant cette version
- Le suivi d'installation recrée une VM avec `n` : après confirmation, il efface la VM, la recrée avec les mêmes paramètres et reprend son suivi sur la même ligne. Chaque déploiement garde désormais les paramètres de création de chaque VM dans `<vm>.spec.json` (mode 0600, il porte l'identité git). L'effacement échoue fermé : un domaine dont l'UUID n'est pas celui de la session, un virsh illisible ou un sudo refusé n'effacent rien. Le lanceur d'une VM effacée en pleine installation est d'abord arrêté, et deux suivis ne peuvent pas recréer la même VM à la fois. VM locales seulement, sessions lancées après cette version
- `F5` dans le suivi d'installation relit tout de suite l'état libvirt, les adresses, les colonnes du tableau et la sonde Odoo de chaque VM, sans attendre leurs périodes (10 s pour l'état, 30 s pour resonder une VM déjà verte). Des appuis répétés ne hâtent jamais la conclusion qu'une VM a été effacée
- Le suivi d'installation restaure une base depuis les actions VM (`a`) : la base « test » est supprimée puis rechargée depuis l'image de la version installée dans la VM, lue dans son `.odoo-version`, crons neutralisés et sans copie `_cache_` sauf si on décoche. Le service erplibre est arrêté autour de l'opération et relancé seulement s'il tournait, et le dossier ERPLibre de la VM est lu dans ce service, ce qui atteint aussi une installation de production sous `/opt`. Rien ne part sans une confirmation qui nomme la base perdue
- Le formulaire de déploiement QEMU garde l'historique de ses modifications : `ctrl+z` défait un pas et `ctrl+y` le refait, de partout dans le formulaire ; `h`, ou F2 depuis un champ texte, liste chaque état avec son heure et ce qui a changé, et Entrée revient à l'un d'eux. Une sélection de masse comme F6 (toutes les versions), voisine de F5, se défait d'un appui, avec les réglages par VM, les verrous et les noms qu'elle avait trouvés. Revenir en arrière puis modifier ne perd rien : l'état quitté est d'abord rejoué. Les touches pressées pendant une restauration l'attendent, et F5 ne déploie donc jamais le plan d'avant une annulation
- Le formulaire de déploiement Proxmox a le même historique, sur les mêmes touches. Le choix « créer un pont » n'est jamais gardé : annuler revient au pont choisi avant, et rien n'est recréé sur l'hôte. Une case 3D offerte en cours de route, une fois le GPU posé sur l'hôte, reste telle quelle à travers une annulation
- Chaque commande git du menu git de TODO s'affiche avant de partir, lectures comprises, en `$ git -C <chemin> …` avec le chemin relatif à la racine ERPLibre et les URL sans utilisateur ni jeton : tirer, synchroniser, mettre à niveau, appliquer, publier, approfondir, geler et comparer les gels. Les lignes vont sur la sortie d'erreur, si bien que le JSON de `script/git/repo_state.py` reste intact ; elles s'affichent quand la sortie d'erreur est un terminal, et `ERPLIBRE_GIT_ECHO=1` ou `0` le force
- Les fichiers compose de Docker installent à chaque démarrage, avant Odoo, les paquets Python que l'image n'a pas : `PIP_EXTRA_REQUIREMENTS_ODOO` les liste pour le venv d'Odoo, celui qu'importent les addons, et `PIP_EXTRA_REQUIREMENTS_ERPLIBRE` pour `.venv.erplibre`, celui de `script/`, une exigence par mot avec sa version au besoin. Une exigence satisfaite ne télécharge rien, et une exigence que pip refuse arrête le conteneur avant Odoo, en nommant la variable. Le conteneur démarre en root, les venvs appartenant à root, puis `docker/entrypoint_pip_extra.sh` lance Odoo sous `odoo` par setpriv ; root ne garde que SETUID et SETGID et `no-new-privileges` empêche Odoo d'en regagner. `docker exec` entre donc en root : `docker compose exec -u odoo ERPLibre bash` garde les fichiers qu'il écrit modifiables par Odoo
- `make odoo_version_remove V=16.0` retire une version d'Odoo : son arbre `odoo<V>/`, son venv, ses projets git-repo sous `.repo/projects/odoo<V>/`, et ses entrées de `.repo/installed_odoo_version.txt` et de `.erplibre-state.json` ; le manifeste local est régénéré, sans quoi le prochain `repo sync` reclonerait l'arbre retiré. `V` prend plusieurs versions pour qu'un stockage partagé ne soit compacté qu'une fois, `DRY=1` affiche le plan, `make odoo_version_remove_odoo_<N>` nomme une version et `make odoo_version_remove_all` les retire toutes, l'active comprise, avant un nouveau clonage. git-repo partage un stockage d'objets par amont entre versions : les stockages qu'aucun projet restant n'utilise sont effacés, et chaque stockage partagé est compacté en place sur l'union de ce qu'atteint chaque projet restant, avec sa propre frontière superficielle, après le retrait des branches des séries non installées dans les projets restants ; sans Odoo 12 à 16, le stockage du cœur d'Odoo est passé de 25 à 5 Gio. Le travail non sauvegardé — arbre modifié, commits absents de tout remote, stash, fichiers hors de tout dépôt — est listé et doit être confirmé en tapant un mot ; la version active est refusée, sauf par `odoo_version_remove_all`, et le Python de pyenv n'est que signalé. TODO › Execute › Développement › [6] Uninstall offre la même chose, plusieurs versions d'un coup par des numéros séparés par des espaces ; les entrées suivantes décalent d'un rang
- `make repo_sync` ramène chaque dépôt à la révision du manifeste local, `make repo_pull` lance le tirage de TODO › Exécution › Git › Repo › Tirer (essai à sec, questions, puis la passe épinglée sur lui), et `make repo_pull_dry_run` montre ce que ferait un tirage, sans autre chose que des fetch
- **TODO › Exécution › Développement › [7] Image Odoo** liste les images de base de `image_db/` d'une version d'Odoo et les regénère toutes en parallèle ou une à la fois, là où n'existaient que des cibles make liées à la version active. Une image se bâtit avec l'Odoo actif : une autre version installée se voit proposer le passage d'abord, une version non installée est refusée, et l'absence de GNU parallel est signalée avant tout départ. Les entrées suivantes de ce menu décalent d'un rang
- `script/update/docker_fix_erplibre_info_docker_erplibre_160.sh`, lancé depuis l'hôte, prépare un conteneur ERPLibre 1.6.0 (Odoo 18) en marche pour les instantanés d'`erplibre_info_git`, dont l'image n'a pas `repo_state.py`. Il mémorise le commit de la racine, extrait `master`, active l'option extra quand ses dépôts sont déjà clonés pour que le manifeste régénéré les garde, ouvre en lecture au compte `odoo` les dossiers `.repo/projects/*.git` que l'image laisse à root en mode 700, sans quoi chaque dépôt d'un instantané est en erreur — les dossiers seulement, si bien qu'overlayfs ne recopie aucun fichier, et `odoo` n'y gagne aucune écriture —, installe `erplibre_info_git` et `erplibre_info_developer_menu`, redémarre et inscrit le commit mémorisé dans le premier instantané. Relancé, il ne change rien. Il s'arrête quand un module manque à l'`addons_path` du conteneur ou n'est pas installé après coup, là où Odoo saute un nom de `-i` inconnu sur un simple avertissement. Le tirage n'est pas préparé : l'image 1.6.0 laisse ses dépôts git à root, et tirer depuis Odoo demande une image construite avec `ERPLIBRE_CODE_OWNER=odoo`, `--dev=all` seul n'y suffit pas ; le dernier message lit les deux conditions dans le conteneur et nomme celle qui manque. Ses étapes root passent par `docker exec --privileged`, qui rend à cette seule commande les capacités que les fichiers compose actuels retirent au conteneur
- `script/git/repo_pull.py --mode instantane --targets FICHIER` ramène chaque clone que nomme un instantané sur son commit, sa branche ou sa HEAD détachée. L'essai à sec classe chaque clone — en recul, hors de son historique, commit introuvable —, récupère un commit absent par son SHA depuis n'importe quel remote, et liste les clones que l'instantané ne nomme pas, jamais touchés. L'application, épinglée comme un tirage, pose `<branche>_avant_retour_<horodatage>` sur HEAD, garde le stash d'un arbre modifié au lieu de le supprimer et déplace la racine en dernier ; `--apply-stash CHEMIN=SHA` réapplique ce stash sans le supprimer. Aucun écran ne l'appelle encore
- **Revenir à cet instantané**, sur la fiche d'un instantané dans `erplibre_info_git_fetch` (Odoo 18) : un essai à sec, puis une application sous la double validation et le `--dev` du tirage, ramènent chaque clone au commit de l'instantané, la racine ERPLibre comprise par défaut, avec une branche de sauvegarde pour chacun ; un module installé dans une version plus récente que l'instantané bloque l'application tant qu'une case ne l'accepte pas. Les stashs qu'un retour ou un tirage garde sont listés sous Paramètres › Technique › ERPLibre › Stashs et réappliqués après une double validation, jamais supprimés. Le manifeste d'Odoo 18 gèle `erplibre_addons` sur le commit qui apporte les modules `erplibre_info`, si bien qu'une image gelée les installe
- **Paramètres › Paramètres généraux › À propos** montre un bloc ERPLibre sous celui d'Odoo (`erplibre_info`, Odoo 18) : la version d'ERPLibre, ce qu'affiche `make version` — le Python d'Odoo et celui de l'outillage, Odoo, Poetry, la clé de version, les modules extra, le contexte mobile et les versions d'Odoo installées —, le commit avec sa branche et `git describe --tags`, le mode du code, commits gelés ou branches, et le copyright de TechnoLibre sous la GNU AGPLv3. Ouvrir la page ne fait que lire des fichiers et lancer des commandes git en lecture seule, 3 s au plus, n'écrit rien, et affiche inconnu pour une valeur illisible
- `make docker_volume_clean` efface les volumes du projet docker compose, toutes les bases, le filestore d'Odoo et sa configuration, après les avoir listés et deux confirmations : un `y`, puis le nom du projet retapé. Toute autre réponse, ou une entrée fermée, n'efface rien ; un volume qui porte encore le nom du projet sans figurer dans `docker-compose.yml` est retiré lui aussi. TODO › Exécution › Docker / Podman › Conteneur ERPLibre › Effacer les volumes lance la même commande
- Images Docker pour arm64 et s390x en plus d'amd64 : `script/docker/docker_build.sh --platform=amd64,arm64,s390x` construit chacune sous émulation QEMU quand elle est étrangère, refuse une architecture non émulée ou que l'image Python ne publie pas, et `--print-platforms` liste celles qu'elle publie. L'architecture de l'hôte garde l'étiquette sans suffixe que lance `docker-compose.yml`, les autres prennent `-<arch>`, et `--push` pousse chacune avec son suffixe puis les réunit dans un manifeste multi-architecture sous l'étiquette sans suffixe. `sudo bash script/install/install_container.sh --multiarch` installe buildx et QEMU pour les quatre familles de distributions. TODO › Exécution › Docker / Podman › Construire l'image d'une version d'Odoo demande les architectures et la sortie, et propose cette installation quand l'émulation manque. Une image s390x n'a pas wkhtmltopdf, aucun n'existant au Qt patché et Debian trixie ne l'empaquetant plus : Odoo y imprime ses rapports en HTML, et son client PostgreSQL, le 17 de Debian, ne sait pas sauvegarder un serveur PostgreSQL 18
- stream_deck : extension GNOME multi-indicateurs (registry, six boutons : controller, pencil, film, ERPLibre, network, device) ; schéma GSettings ; auto-login KeepassXC + Selenium / xdotool ; découverte SSH ; sync Git des préférences ; sauvegarde/restauration ; i18n FR/EN.
- ERPLibre Home s'installe sans Odoo, en deux niveaux, par `script/install/install_erplibre_home.sh` sur Debian, Ubuntu, Fedora, AlmaLinux, Rocky Linux, openSUSE et Arch Linux avec GNOME Shell 45 à 51. La base lie l'extension GNOME, compile ses schémas et ses traductions par `msgfmt --check` et l'active ; `--stream-deck` ajoute les paquets USB, une règle udev `uaccess` et `.venv.streamdeck`. `--uninstall` défait l'un ou l'autre niveau, `--dry-run` affiche le plan, et un système non supporté sort en 2 avec une ligne `UNSUPPORTED:`. `make erplibre_home_install` et `make erplibre_home_streamdeck_install` lancent les mêmes commandes
- `TODO › Exécution › Stream Deck` installe l'un ou l'autre niveau sur le poste local, et montre la raison `UNSUPPORTED` de l'installateur en une ligne
- `--stream-deck` écrit aussi l'unité `systemd --user` `erplibre-home-streamdeck.service`, qui lance le programme du deck choisi par `--deck-program` (le window tiler par défaut) quand un deck est branché, et à l'ouverture de session avec `--autostart`. Une installation qui omet une option garde le réglage courant. Les jeux lancés depuis TODO ou la galerie l'arrêtent et la relancent à leur fin, sauf avec `--no-restart-after-game`. Un verrou, pris par le tiler et le contrôleur, et par la passation pour un jeu, qui le garde tant qu'un de ses processus tourne, fait sortir un second programme du deck, le service compris, avec le code 2, en nommant celui qui tient le deck. Le service abandonne après cinq démarrages ratés en une minute, et s'arrête proprement, le deck remis à zéro. **Démarrer le programme du deck**, dans le panneau des appareils, lance l'unité et, un instant plus tard, dit pourquoi aucun programme du deck ne tourne : le programme qui tient le deck, aucun Stream Deck à écran, la raison du démarrage sauté, ou le code de sortie d'un programme qui a planté et attend sa relance
- `TODO › Exécution › Stream Deck` est un sous-menu : les jeux, les deux installations (celle du Stream Deck demande le programme, le démarrage automatique, la relance après un jeu et les outils facultatifs, chacun proposé avec le réglage courant, puis affiche sa commande), le service et son programme, le démarrage automatique, un état, un diagnostic qui nomme la commande corrigeant chaque problème, les deux désinstallations, et le rechargement et les préférences de l'extension
- Deux outils de VM QEMU, `erplibre_home` et `erplibre_home_streamdeck`, lancent l'installateur après le bureau GNOME ; le profil d'installation « ERPLibre Home (sans Odoo) » installe la base seule, sans service Odoo
- `long_test/install_erplibre_home.py`, aussi dans le menu des tests longs, crée une VM de bureau par système supporté, y installe HEAD depuis un bundle git, et exige que GetExtensionInfo dise l'extension ACTIVE ; cinq étapes installent ensuite, désinstallent en partie puis en entier, et réinstallent sur la même VM, et le journal de chaque système nomme chaque contrôle et son issue
- `long_test/mobile_sync.py`, aussi `make test_mobile_sync` et le menu des tests longs, fait tourner le code de synchro de l'app mobile contre des Odoo 16, 17 et 18 jetables, rapidement une fois les gabarits construits ; `--appareil` joue aussi ses écrans sur le téléphone branché, dans une app de test à part qui laisse celle de l'utilisateur intacte
- `long_test/mobile_sync.py` teste aussi le clavardage mobile sur Odoo 18 (`--versions 18 --filtre chat`) : un second utilisateur, `chat_user`, et le module `erplibre_mobile_chat` sont dans le gabarit de la 18, `chat.test.ts` et `chatRealtime.test.ts` vérifient envois, réponse perdue, file hors ligne, historique, marques de lecture, bus et frappe contre le vrai serveur, et `--appareil` ajoute un écran « clavardage »
- `contracts/odoo-api.json` décrit les routes du clavardage, le bus websocket, les tables du clavardage et la règle d'idempotence des envois ; `contracts/compatibility.json` liste le module facultatif `erplibre_mobile_chat`, qui stocke une fois un envoi fait deux fois, l'app se rabattant sur un commentaire marqueur sans lui
- `long_test/mobile_sync.py` teste aussi le lot 2 du clavardage mobile (`--filtre chat`) : `chatManage.test.ts` relit sur le vrai Odoo 18 le message direct créé une fois, le groupe créé hors ligne puis l'app relancée, la réponse perdue (avec le module et par empreinte), les groupes d'accès des canaux, l'adhésion, l'invitation, le renommage, le départ, la conversation masquée, les sourdines et le retrait d'un membre ; `--appareil` crée un groupe depuis le téléphone ; les gabarits de la 16, de la 17 et de la 18 créent d'avance les réglages de chaque utilisateur interne
- `contracts/odoo-api.json` ajoute les appels du lot 2 du clavardage (création d'un message direct, d'un groupe et d'un canal, adhésion, invitation, renommage, description, départ, masquage, sourdine, sourdine globale, retrait, membres, personnes), les genres de synchro qui les mettent en file, et les nouvelles colonnes, `chat_temp_ids` et les migrations 2026102601 à 2026102603 ; `contracts/compatibility.json` passe `erplibre_mobile_chat` à 18.0.1.1.0, qui crée un groupe ou un canal une fois par uuid client (verrou et index uniques partiels) et ajoute `erplibre_remove_member`, réservé aux administrateurs
- `long_test/mobile_sync.py` teste aussi le lot 3 du clavardage mobile (`--filtre chat`) : `chatAttachments.test.ts` relit sur le vrai Odoo 18 le téléversement à réponse perdue (y compris celui d'une photo que la route d'Odoo redimensionne), un envoi de deux fichiers, les fichiers vocaux, l'original d'une photo, la limite de téléversement abaissée avant et après la mise en file (dans des fichiers `*.serial.test.ts`, lancés dans une seconde passe), le Wi-Fi seulement, une session expirée et l'image d'un interlocuteur ; `--appareil` ajoute l'écran « pièces jointes du clavardage », vérifie que le clavier reste ouvert sur trois envois de suite dans une conversation, et que l'app de l'utilisateur reste intacte ; le test unitaire du banc se lance par `.venv.erplibre/bin/python -m unittest discover -s test -p test_mobile_sync_harness.py`
- `contracts/odoo-api.json` ajoute les appels du lot 3 du clavardage (téléversement sur les deux routes avec son jeton CSRF, recherche d'un téléversement perdu, aperçus, téléchargements, notification de suppression, `attachment_ids` dans un envoi), les tables `chat_attachments` et `chat_drafts` et les migrations 2026102604 à 2026102606 ; `contracts/compatibility.json` passe `erplibre_mobile_chat` à 18.0.1.2.0, qui rend idempotent le téléversement d'une pièce jointe par uuid client et garde l'original d'une photo
- `long_test/mobile_sync.py` teste aussi le lot 4 du clavardage mobile (`--filtre chat`) : `chatActions.test.ts` relit sur le vrai Odoo 18 une réaction à réponse perdue, une réaction ajoutée puis retirée hors ligne, une modification qui garde les fichiers, une modification à réponse perdue reprise comme faite et suivie d'une correction, une modification tardive refusée sur les deux routes, une suppression et une réponse dont le parent est supprimé entre-temps ; `chatWriting.test.ts` vérifie la notification d'une mention, `@everyone`, le lien de canal et que le HTML de l'app reste stocké tel quel après une modification dans le navigateur ; `long_test/mobile_sync_composer.py` produit les références du composeur avec le formateur même d'Odoo 18 dans un Chromium sans écran ; `--appareil` ajoute l'écran « actions du clavardage » et vérifie que la zone de saisie reste à 16 px au plus au-dessus de la barre de navigation
- `contracts/odoo-api.json` ajoute les appels du lot 4 du clavardage (réaction à action explicite, modification sur les deux routes avec son empreinte, suppression, suggestions de mention, notification de suppression de message, `partner_ids`, `special_mentions` et `parent_id` dans un envoi), la table `chat_reactions` et les migrations 2026102607 et 2026102608 ; `contracts/compatibility.json` passe `erplibre_mobile_chat` à 18.0.1.3.0, qui ajoute l'empreinte du corps d'un message et une route qui ne modifie un message que s'il n'a pas changé depuis la lecture de l'app
- `long_test/mobile_sync.py` teste aussi le lot 5 du clavardage mobile (`--filtre chat`) : `chatFinding.test.ts` vérifie sur le vrai Odoo 18 qu'une recherche serveur ne voit que les canaux dont l'utilisateur est membre (jamais un canal public non rejoint, jamais les conversations des autres), avec le module et sans lui, que `&` et `%` dans un terme trouvent les mêmes messages que sur le téléphone, qu'ouvrir un résultat plus ancien que l'historique chargé charge les pages avec `around` sans rien marquer lu, qu'une épingle et un favori à réponse perdue ne sont faits qu'une fois, et un favori posé dans le navigateur entre-temps ; `chatInbox.test.ts` tourne sous un `inbox_user` créé d'avance et vérifie les trois genres d'éléments, « marquer lu » et « tout marquer lu » (une mention arrivée après l'appui reste non lue), une réponse sur une tâche en note (aucun `mail.mail`) et en message (un pour l'abonné notifié par courriel) avec une photo, une réponse dont les réponses du téléversement puis de l'envoi sont perdues, des éléments qui arrivent dans la boîte par le bus sans lire de page, et le passage d'un utilisateur notifié par courriel à la boîte. Le SMTP des serveurs d'essai pointe sur un port local fermé : une notification reste un `mail.mail` et ne quitte jamais la machine ; `--appareil` ajoute l'écran « recherche et boîte du clavardage » et vérifie la ligne d'auteur des bulles d'un groupe
- `contracts/odoo-api.json` ajoute les appels du lot 5 du clavardage (recherche serveur et son repli, épingle et liste des épinglés, favori et liste des favoris, boîte de réception, historique et marquage lu, réponse dans le fil d'un enregistrement avec ses fichiers, la préférence de notification et son changement, la route de l'avatar de l'auteur), les tables `chat_mailbox`, `chat_on_top`, `chat_search_fts` et `chat_avatars` et les migrations 2026102701 à 2026102705 ; `contracts/compatibility.json` passe `erplibre_mobile_chat` à 18.0.1.4.0, qui ajoute une route de recherche limitée aux membres, un favori idempotent, le dédoublonnage des envois sur tout modèle `mail.thread` et le champ de niveau `erplibre_chat_level`
- Le clavardage mobile, lot 5 : conversations gardées en tête (réglage « Ordre de la liste » : « Épinglées d'abord » ou « Non lues d'abord »), recherche locale (FTS5 trigramme sur le téléphone, LIKE en repli) puis recherche serveur, messages épinglés, favoris, boîte de réception (mentions, enregistrements suivis, assignations, historique, marquer lu et tout marquer lu), ouverture d'un élément dans la note de l'app ou dans la vue web, réponse dans le fil d'un enregistrement avec fichiers, voix et mentions (note par défaut, message après confirmation), explication et bouton pour l'utilisateur notifié par courriel, correction d'une livraison de la boîte rattrapée par un chargement, nom et avatar de l'auteur sur les bulles des autres dans les groupes et canaux (migrations 2026102701 à 2026102705)
- Les notifications du clavardage app fermée d'ERPLibre Home Mobile passent par le ntfy de l'utilisateur : `TODO › Déployer › Infrastructure d'appel › Préparer ntfy pour ERPLibre mobile` (sur cette machine ou par ssh) pose les règles d'accès, crée un compte et un jeton de téléphone en lecture seule sur un préfixe secret, et montre le lien de configuration en code QR ; le même menu liste les téléphones préparés et en révoque un. La ligne de commande de ntfy prend `--config` avant la sous-commande pour `user` et `token`
- `long_test/mobile_sync.py` joue le push du clavardage contre un ntfy jetable qui lui est propre (`--filtre push`), et sur le téléphone avec `--appareil` (notification, forme de l'écran verrouillé, service revenu après un plantage, sommaire direct d'Odoo), sans toucher au ntfy de la machine
- `contracts/odoo-api.json` ajoute les appels du push du clavardage (enregistrement, formes de charge utile, sommaire, accès ntfy) et la table `chat_push` ; `contracts/compatibility.json` note que le push fonctionne avec `erplibre_mobile_chat` 1.4 ou sans
- Les notifications de clavardage d'ERPLibre Home Mobile gagnent des actions et `erplibre_mobile_chat` 1.5 : trois boutons par notification de clavardage (« Répondre » et « Marquer lu » toujours, puis « 👍 » quand le plus récent message a un identifiant, sinon « Muet 1 h »), enregistrés avant tout appel réseau et envoyés une fois, confiés à l'app par une notification par serveur quand la session est morte ; le module marque les appareils de l'app, ajoute l'identifiant du message et le type de canal à leurs push, les envoie après la validation avec le 200 de ntfy accepté et aucun point de terminaison journalisé, et ajoute les push « lu » et `inbox_done` aux seuls appareils de l'app, avec une option de silence tant qu'un navigateur est en ligne pour une prochaine version
- `long_test/mobile_sync.py` joue aussi les actions du push du clavardage (`--filtre push`) : `chatPushModule.test.ts` pour le module 1.5 (appareils marqués et non marqués, les push « lu » et `inbox_done`, l'appareil silencieux) et `chatPushActions.test.ts` pour une action confiée à l'app ; `--appareil` ajoute le scénario « actions du clavardage, app tuée », dont les touchers restent bornés à la ligne de notification de l'app de test et ne partent que là où deux relevés de suite s'accordent
- `contracts/odoo-api.json` ajoute `chat.push.actions` et `chat.push.module` et les formes 1.5 de `chat.push.payload` ; `contracts/compatibility.json` passe `erplibre_mobile_chat` à 18.0.1.5.0 (sans lui : pas de 👍, une lecture trouvée par la date, pas de push de lecture, et un avertissement d'Odoo pour chaque push que ntfy répond par 200)
- La conception des notifications de clavardage (`docs/superpowers/specs/2026-10-28-erplibre-mobile-chat-notifications-design.md`) : le lot 2 est marqué fait, et « une action dont la session a expiré » devient la notification de reprise qui ouvre l'app au toucher, Android interdisant à l'app de s'ouvrir seule
- Les notifications du clavardage d'ERPLibre Home Mobile reçoivent leurs préférences et `erplibre_mobile_chat` 18.0.1.6.0 : le réglage des canaux d'Odoo changé depuis l'app (général et par canal), un filtre du téléphone et des heures calmes par serveur, un seul choix pour le navigateur actif sur le téléphone (sonner tout de suite, attendre 10 s, ne pas envoyer), et la montée automatique sous l'économiseur et sur batterie faible, qui ne dépasse jamais le niveau 4 ; le module marque chaque appareil de son mode du navigateur et ajoute à la charge v 2, pour chaque destinataire, si l'utilisateur est mentionné et si un de ses navigateurs a été actif dans les 5 minutes
- `long_test/mobile_sync.py` joue aussi les préférences du push du clavardage (`--filtre push`) : `chatPushPrefs.test.ts` pour les réglages d'Odoo changés depuis l'app et le navigateur, le mode de l'appareil et la charge v 2 ; `--appareil` ajoute le scénario « préférences du clavardage, app fermée », qui simule la batterie et l'alimentation par la porte de l'app de test, et `--batterie-reelle` les change pour tout le téléphone, sur un téléphone de test vide seulement, et les rend ensuite
- `contracts/odoo-api.json` ajoute `chat.settings.notify` (`/discuss/settings/custom_notifications`, « mentions » écrit false, la valeur générale pour les canaux seulement, les échos du bus) et l'argument de route et la charge v 2 du module 1.6 ; `contracts/compatibility.json` passe `erplibre_mobile_chat` à 18.0.1.6.0 (sans lui : les messages de canal passent le filtre « mentions », « attendre » sonne tout de suite, « ne pas envoyer » prend le délai d'absence de 30 minutes d'Odoo de la 1.5)
- La conception des notifications de clavardage : le lot 3 est marqué fait avec le module 1.6, et les décisions sur les seuils de batterie, le choix du navigateur actif, le filtre du téléphone et les heures calmes disent ce qui a été construit
- `TODO › Déployer › Infrastructure d'appel` installe les serveurs dont les appels ont besoin, coturn (TURN) et ntfy, sur un hôte Debian, Ubuntu ou Arch Linux, sur cette machine ou par ssh, depuis les paquets de la distribution sous systemd, en mode développement : TLS « aucun » (http et TURN sans TLS, affiché comme réseau local seulement) ou un certificat et une clé fournis, remis aux deux services. Les ports sont demandés : TURN 3478 udp et tcp, TURNS 5349 avec un certificat, relais 49152 à 49252 udp, ntfy 8080 en http et 8443 en https ; les plages d'adresses privées restent joignables par le relais dans ce mode développement (l'installateur reçoit `TURN_ALLOW_PRIVATE=1`), et l'écran le dit. Rien ne s'exécute avant que le plan soit montré et accepté ; un autre système, un hôte sans systemd, un port qu'un autre programme tient (nommé), et un certificat qui ne correspond pas à sa clé, expiré ou sans le nom de l'hôte sont refusés avant toute installation. Un refus de sudo est reconnu dans toutes les langues. Une deuxième installation avec les mêmes réponses dit « rien à changer »
- Les identifiants de coturn vivent dans sa propre base d'utilisateurs SQLite (`/var/lib/erplibre-call/turndb`), jamais dans `turnserver.conf`, avec un seul compte de contrôle `erplibre-check`, dont le mot de passe est tiré sur l'hôte et dont seule la clé est gardée. L'hôte garde le seul relevé de ce que l'outil a fait dans `/etc/erplibre-call/state.json` (root, 0600), écrit une fois chaque service actif ; aucun secret ne reste sur la machine qui exécute TODO, et le mot de passe d'administration de ntfy est montré une fois
- Une configuration de coturn ou de ntfy que l'outil n'a pas écrite est adoptée, pas écrasée : montrée en diff unifié, sauvegardée en `<fichier>.bak-<horodatage>` et consignée ; les utilisateurs et jetons de ntfy restent
- L'infrastructure d'appel n'active jamais de pare-feu et ne touche pas à la règle de ssh : à un ufw ou un nftables actif, elle ne fait qu'ajouter des règles d'autorisation pour les ports choisis, après les avoir montrées et obtenu un oui, et consigne chacune au passage root qui la pose ; une relance sans rien à changer propose encore les règles absentes de l'état ; le pare-feu du fournisseur infonuagique est rappelé
- `Infrastructure d'appel › Vérifier` éprouve l'hôte depuis cette machine : une vraie allocation TURN avec le compte de contrôle en udp, en tcp et, avec un certificat, en TLS (une allocation accordée sans identifiants est signalée comme relais ouvert), la santé de ntfy, les jours restants du certificat, les règles de pare-feu consignées et les deux services ; un fichier d'autorité de certification qui ne se charge pas est refusé avant la vérification
- `Infrastructure d'appel › Désinstaller` défait ce que l'état de l'hôte consigne : ses règles de pare-feu sont retirées, y compris celles d'un passage coupé avant l'écriture de son état ; une configuration adoptée est restaurée depuis sa sauvegarde et son paquet gardé, son unité laissée arrêtée ou désactivée comme elle a été trouvée, et le compte d'administration que l'installateur a ajouté à un ntfy adopté retiré ; un paquet que l'outil a installé est purgé, et une configuration qu'il avait adoptée avant de poser ce paquet est remise ; et les données de ntfy et les certificats sont gardés sauf si l'utilisateur demande le contraire. Sans état, elle dit « Rien à désinstaller. » et ne change rien
- `Infrastructure d'appel` gagne un mode production, choisi juste après les services (« Production : noms publics, nginx devant ntfy, certificat reconnu »). Il demande un domaine, un nom à points et jamais une adresse IP (« La production demande un nom de domaine (example.org), pas une adresse IP. »), d'où découlent les noms `ntfy.<domaine>` et `turn.<domaine>`, chacun modifiable, puis la source du certificat : Let's Encrypt ou un certificat fourni, la production refusant de tourner sans (« La production exige un certificat : Let's Encrypt ou un certificat fourni. »). ntfy n'écoute que sur 127.0.0.1, derrière nginx, avec `behind-proxy: true`, `base-url: https://ntfy.<domaine>` sans port, et son interface web coupée sauf si « Interface web de ntfy sur son nom public ? » reçoit un oui ; nginx tient les ports 80 et 443 et renvoie le http vers le https. coturn garde 3478 udp et tcp, TLS sur 5349 et les relais 49152 à 65535 par défaut ; son TLS passe sur 443 au lieu de 5349 seulement sur un hôte sans nginx dont le port 443 est libre, après un oui à « TURN sur TLS sur le port 443 au lieu de 5349 ? », et un complément d'unité systemd propre à l'outil (`AmbientCapabilities=CAP_NET_BIND_SERVICE`) lui permet de prendre ce port. Les règles de pare-feu proposées gagnent 80 et 443 pour nginx, ou 80 pour certbot seul ; avec Let's Encrypt par HTTP, elles sont proposées avant l'installation, pour que le port 80 soit ouvert quand le défi arrive
- Let's Encrypt en production : certbot obtient un seul certificat pour les deux noms (`--cert-name erplibre-call`), toujours par un essai à blanc sur l'environnement de test d'abord (`certbot certonly --dry-run`, mêmes arguments), l'émission réelle ne venant qu'une fois l'essai réussi ; un échec s'arrête là avec la dernière ligne d'erreur de certbot, et l'état ne revendique aucun certificat Let's Encrypt. Le courriel est demandé ; sans courriel, certbot s'inscrit avec `--register-unsafely-without-email` et l'écran dit « Sans courriel, Let's Encrypt ne pourra prévenir de rien : ni d'un renouvellement qui échoue, ni d'un problème de compte. ». Le défi est HTTP-01, par le webroot de nginx `/var/lib/erplibre-call-acme`, ou par certbot seul sur le port 80 (`--standalone`) sur un hôte coturn seul sans nginx, ou DNS-01 par un greffon DNS de certbot parmi cloudflare, digitalocean, dnsimple, google, linode, luadns, nsone, ovh et rfc2136, dont seuls ceux que le système de l'hôte fournit en paquet sont proposés (« Seuls les greffons que <système> fournit en paquet sont proposés. » ; sur Debian 13 : cloudflare, google et rfc2136). Le fichier d'identifiants du greffon est lu sur la machine qui exécute TODO, jamais affiché, voyage dans le corps du script root et arrive dans `/etc/erplibre-call/dns/<greffon>.ini`, root 0600. Le greffon `--nginx`, qui modifie les configurations, n'est jamais employé. Avant le oui, chaque nom qui ne résout pas, ou résout vers ni l'hôte ni son IP publique, est nommé, avec « Le défi HTTP de Let's Encrypt échouerait : corrigez le DNS avant d'installer. » sous un défi HTTP. Le renouvellement part du minuteur certbot fourni par le système, activé s'il ne l'était pas, ou du minuteur propre à l'outil `erplibre-call-certbot.timer` quand le système n'en fournit aucun ; une relance dont les noms n'ont pas changé garde le certificat sans nouvel essai à blanc
- Le crochet de déploiement du renouvellement `/etc/letsencrypt/renewal-hooks/deploy/erplibre-call` n'agit que pour la lignée `erplibre-call`, et ne change rien pour une autre : il copie le certificat et la clé renouvelés vers `/etc/erplibre-call/tls/turn.{crt,key}` de coturn, envoie SIGUSR2 à coturn, qui recharge son certificat sans redémarrer, et recharge nginx après `nginx -t`. Sous un certificat fourni, il laisse coturn tranquille
- nginx en production est installé s'il est absent ; présent, l'outil y ajoute son propre site, `erplibre-call-ntfy.conf`, et ne touche à aucun autre : dans `sites-available/` avec son lien dans `sites-enabled/` (Debian, Ubuntu), dans `conf.d/` quand `nginx.conf` n'inclut que ce dossier, sinon dans `/etc/nginx/erplibre-call.d/`, que lit une ligne `include` dans le `http {}` de `nginx.conf` (Arch), cette ligne montrée en diff, sauvegardée et ajoutée seulement après le oui. Chaque changement est suivi de `nginx -t` ; un test qui échoue remet les fichiers de l'outil avant que quoi que ce soit ne se recharge, et nginx est rechargé, jamais redémarré. Un nom qu'un autre site sert déjà est refusé avant toute installation (« nginx sert déjà « <nom> » dans <fichier>, un site que l'outil n'a pas écrit : rien n'est touché. »)
- Un hôte derrière un NAT : quand le nom TURN résout vers une adresse absente des interfaces de l'hôte, le menu la propose comme `external-ip` de coturn (« IP publique <adresse> ? (Entrée pour confirmer, ou tapez la bonne) : ») ; un nom qui ne résout nulle part fait demander l'IP publique, obligatoire. Les plages d'adresses privées restent refusées au relais en production
- `Infrastructure d'appel › Vérifier` en production vérifie aussi TURN sur TLS sur son nom auprès des autorités du système, demande un relais vers une adresse privée et en attend le refus (« Plages privées refusées »), joint la santé de ntfy par nginx sur 443 sous son nom, lit l'émetteur du certificat, un certificat de test de Let's Encrypt étant signalé (« certificat de TEST de Let's Encrypt (<émetteur>) : aucun client ne le reconnaît »), et contrôle le renouvellement : le crochet exécutable, le fichier de renouvellement en place, le minuteur actif
- `Infrastructure d'appel › Désinstaller` en production retire d'abord le crochet de déploiement, puis le site nginx, son lien et la ligne `include` (la sauvegarde de `nginx.conf` n'est remise que si elle est identique, si bien que les modifications ultérieures restent), le dossier ACME, les identifiants DNS et le minuteur que l'outil a ajouté, gardé tant qu'un autre certificat de l'hôte en a besoin ; nginx, certbot et les greffons DNS ne sont purgés que si l'outil les a installés et que rien d'autre ne s'en sert, certbot restant tant que le certificat reste. Un nginx déjà présent est laissé arrêté ou désactivé comme il a été trouvé. Le certificat Let's Encrypt est gardé sauf si « Supprimer aussi les certificats et la base des comptes de ntfy ? (o/N) » reçoit un oui : gardé, son fichier de renouvellement est déplacé en `<fichier>.erplibre-hold` pour que le minuteur cesse de le renouveler, et une réinstallation le remet en place
- `long_test/call_infra.py` (tests longs de TODO, entrées 16 et 17) installe, vérifie, réinstalle et désinstalle l'infrastructure d'appel sur des VM jetables, en deux scénarios (`--scenario dev|prod`, les deux par défaut). Développement : Debian 13 avec un ufw actif, un ntfy déjà en place à adopter et un certificat fourni, et Arch Linux sans TLS. Production, sur les deux systèmes : des noms sous `call.exemple.test`, nginx installé devant ntfy, un certificat fourni, et le crochet de déploiement du produit lancé à la main sur une lignée de substitution, coturn devant servir le nouveau certificat sous le même processus. Ensuite les ports doivent être fermés et une deuxième désinstallation ne doit rien trouver. Il mène les étapes mêmes du menu, et ses journaux masquent le mot de passe d'administration, la clé de contrôle et le jeton ntfy du téléphone

## Modifié

- Le formulaire de déploiement liste son catalogue par ordre alphabétique de système, puis par version comparée comme un nombre — ubuntu 26.04 après 24.04, almalinux 10 après 9 —, puis par architecture. La liste en ligne de commande garde son ordre, ses numéros étant ceux qu'on retape

- Le programme du deck Stream Deck passe du fichier `script/stream_deck/erplibre_streamdeck.py` au répertoire-paquet `script/stream_deck/erplibre_streamdeck`, lancé par `python script/stream_deck/erplibre_streamdeck` : un noyau et un plugin par fonction. Les pages et les touches restent les mêmes à toute géométrie, avec un changement voulu : un appui sur une tuile du tableau de bord ouvre ce que la touche montrait, même si les sessions ont changé depuis son affichage
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
- L'environnement virtuel d'outillage `.venv.erplibre` tourne en Python 3.15.2, indépendamment de celui d'Odoo (3.12.16 pour Odoo 18.0). `install_erplibre.sh` le bâtit par `install_venv.sh` et `EL_PYTHON_PROVIDER` plutôt qu'avec le `python3` du système
- `.venv.erplibre` sur un Python incompatible est SUPPRIMÉ puis rebâti ; ce qu'on y avait posé à la main part avec lui. Le venv d'Odoo est conservé quand seule sa version diffère, et rebâti seulement s'il est hors service : le rebâtir refait une installation Poetry entière. Un répertoire sans `pyvenv.cfg` n'est jamais effacé
- `make` et `make todo` lancent `./todo.sh`, dont le nom annonce un menu et non une installation ; il passe chaque argument à `install.sh`, qui choisit un interpréteur capable de LIRE le code avant de le lancer : `.venv.erplibre` s'il porte la bonne version, sinon le `python3` du système s'il est assez récent, sinon l'installation, qui ne part que sur un oui tapé au terminal (`o`, `oui`, `y`, `yes`) puisqu'elle peut supprimer `.venv.erplibre`. Un système plus ancien que `conf/python-erplibre-version` s'arrêterait autrement sur une erreur de syntaxe levée avant qu'aucun garde puisse nommer la commande à taper. TODO se relance ensuite dans `.venv.erplibre`, ou propose de lancer `install_erplibre.sh` en terminal
- L'image Docker de production bâtit `.venv.erplibre` sur le Python d'Odoo à partir de ses propres requis, `requirement/erplibre_require-ments-docker.txt` — les six paquets qu'importent ses deux points d'entrée Python — et s'arrête en nommant le coupable quand ces points d'entrée ne s'importent pas. La liste de l'hôte, écrite pour 3.14, barrerait toute image d'Odoo 12 à 15
- Debian 11 quitte le catalogue de déploiement : son LTS est terminé, et sa suite de sécurité n'est ni servie ni archivée — l'index qu'elle publie encore nomme des paquets dont le pool ne porte plus le fichier, et apt s'arrête avant d'installer git. Debian 13 la remplace, son image cloud étant toujours le dernier point de version
- Toutes les images de conteneur reposent sur bookworm, quelle que soit la version d'Odoo. La base est `python:<version>-slim-<version Debian>` : l'interpréteur vient de l'image officielle, jamais de Debian, et les variantes bookworm existent jusqu'à 3.7.17. Le build de wkhtmltopdf suit la version — celui de bullseye réclame libssl1.1, absente de bookworm
- Le PATCH ne borne que le venv d'Odoo, dont le pyproject exige `>=3.12.10,<3.13`. Pour celui de l'outillage, la majeure.mineure suffit : exiger le patch écartait le Python d'une distribution d'un cran en retard — NixOS 25.11 livre 3.14.2 quand conf demande 3.14.7 — et faisait COMPILER CPython à pyenv pour une différence que rien ne réclame
- `make format` choisit le formateur d'après le contexte de chaque fichier : un module Odoo garde isort et black en `py37`, la série la plus ancienne encore supportée, quand l'outillage de ce dépôt passe par ruff, réglé une fois dans `.ruff.toml`. ruff suit les versions de CPython, là où black 24.8.0 s'arrête à `py313`, et son tri d'imports remplace isort ; c'est aussi ce qu'emploie la norme OCA depuis qu'elle a quitté black
- Les dépôts que Google Repo rapatrie sous `script/` sont écartés de ce formatage, chemin nommé compris : les reformater écrirait dans l'historique d'autrui. `target-version` y reste à `py310`, parce que les hooks git portent `#!/usr/bin/env python3` et qu'une distribution livre encore 3.10 — à partir de 3.14, ruff écrirait `except A, B:` sans parenthèses
- La liste des commandes Claude Code de `TODO › Execute › GPT code › Claude configs` compare chaque gabarit d'ERPLibre de `conf/` à sa copie de `~/.claude/commands/` : une commande non installée est affichée, une copie périmée est marquée de son compte de lignes ajoutées et retirées, et une commande venue d'ailleurs est signalée comme telle. Sur un oui, elle affiche le diff, puis redéploie les copies périmées en gardant le nom et le courriel git que portait `/commit`
- Un message de commit s'ouvre sur un sujet et un corps en anglais ; `--- FR ---` ouvre ensuite la section française, qui commence par le sujet traduit sous le même tag. Le hook `commit-msg` refuse un marqueur `--- EN ---` et une section française sans ce titre, et juge ce titre comme un sujet. `/commit` et `/git_prepare_merge` suivent le même ordre
- Menus de TODO : la langue se règle seulement depuis Configuration, l'entrée en double dans Execute disparaît, et Fork quitte le menu principal pour Configuration. Le menu principal numérote désormais Télémétrie 4 et Configuration 5. Le choix de la langue montre un drapeau par langue
- Dépendances d'Odoo 18 rafraîchies. `openai` est épinglé en 2.x, dont la 3.x exige un `idna` qu'Odoo 18 interdit ; `fsspec` est épinglé à côté de `s3fs`, qui l'exige à sa propre version exacte, si bien que les deux se montent ensemble ; `meteostat` revient en 1.x, toute 2.x plafonnant `pytz` sous 2024. PyMuPDF reste écarté sur s390x, désormais déclaré dans les requirements pour qu'une régénération le garde. Les montées majeures de `ujson` 6, `plotly` 7, `python-slugify` 9 et `sqlalchemy` 2.1 ne sont pas encore testées
- Dependabot ignore les versions majeures de `meteostat`
- Odoo 18 passe à pandas 3.0.6, cryptography 50 avec pyopenssl 26.4, Pillow 12.3 et botocore/boto3 1.43.75 avec aiobotocore 3.9.1, le plus haut botocore que sa plage étroite accepte. Les sept modules qui importent pandas exécutent leurs appels pandas sans changement ; `freq='d'` dans un tableau de bord de présence Cybro avertit désormais et cassera avec pandas 4
- Dependabot réunit `aiobotocore`, `botocore` et `boto3` dans une seule demande de fusion, chaque aiobotocore n'acceptant qu'une plage étroite de botocore ; les correctifs de sécurité arrivent toujours seuls
- `TODO › Transform data` lit Excel avec openpyxl 3.1.5 et xlsxwriter 3.2.9 ; le test de fuite qui garde l'épingle exacte d'openpyxl passe sur eux
- factur-x exige 6.8 hors s390x, la version déjà verrouillée : une régénération ne peut plus retomber sur une 4.x ou 5.x non testée
- Le choix d'interface du déploiement QEMU et de la migration Odoo, et ses préférences dans `TODO › Configuration`, marquent le formulaire TUI d'un 📋 et les questions ligne par ligne d'un 💬
- `make test_unit` lance les fichiers de tests en parallèle, un par cœur (`UNIT_JOBS`), les plus longs d'abord d'après les durées du passage précédent : la suite passe d'environ 8 minutes à environ 35 s sur 16 cœurs. Chaque fichier tourne sans terminal de contrôle et avec `/dev/null` en entrée, `sudo`, `pkexec`, `doas`, `virsh`, `ssh` et `adb` sont remplacés par des commandes qui refusent, et un fichier est arrêté après `UNIT_TIMEOUT` secondes (300) : un test qui échappe à ses doublures échoue au lieu de demander un mot de passe, d'interroger les VM du poste ou d'atteindre le téléphone qui y est branché
- `./script/test/run_unit_test.sh --tui` montre chaque fichier de tests en attente, en cours ou fini avec sa durée, et la fin du journal du fichier choisi. Sans lui, un fichier encore en cours après `UNIT_SIGNAL` secondes (60) est annoncé, et Ctrl+C arrête les fichiers en cours et les nomme
- `TODO › Test` n'a plus qu'une entrée de tests unitaires, qui lance toute la suite par ce lanceur et son tableau : les entrées séparées courriel et analyse disparaissent, et les tests longs passent de [6] à [4]
- Le proxy SOCKS de `TODO › Deploy` propose le premier port local libre dès 1080, et un port occupé choisi à la main passe au suivant libre, annoncé ; le mode d'emploi du navigateur nomme le port réellement ouvert
- TODO ne charge `openai`, `urwid` et `pykeepass` que lorsque l'assistant, le navigateur de fichiers ou le coffre s'en servent : l'import de TODO prend environ six fois moins de temps, à chaque lancement
- La suite unitaire prend moins de temps : les tests de progression du déploiement attendent une condition plutôt qu'une durée fixe, les tests Textual tournent sans le mode debug d'asyncio, et les tests KeePass remplacent Argon2 par une dérivation rapide, un test gardant la vraie
- La synchronisation des dépôts affiche sa progression par défaut : dépôts terminés, dépôts en cours, temps écoulé. Silencieuse, elle laissait un gros dépôt se télécharger pendant des dizaines de minutes sans un caractère à l'écran, ce qui passait pour un blocage. `EL_VERBOSE=1` ajoute toujours les logs détaillés
- `odoo/documentation-user` est cloné à la profondeur 1 pour Odoo 12 à 18 : tout l'historique de la documentation d'Odoo, images comprises, ne domine plus la synchronisation
- Le lock d'Odoo 18 est rafraîchi (27 paquets, dont factur-x 7 et plaid-python 45) ; `python-dotenv` quitte le venv d'Odoo, seul un fichier d'exemple sous `doc/examples` le demandant
- Le lanceur des tests unitaires donne à chaque fichier son propre `TMPDIR`, retire ce qu'il y laisse et le nomme au bilan : les temporaires oubliés ne s'accumulent plus dans `/tmp` jusqu'à épuiser les inodes d'un tmpfs
- Les VM s390x se déploient depuis Ubuntu, Debian (par debian-installer), Fedora 43, AlmaLinux, Rocky et openSUSE, et reçoivent 4 Gio de RAM quand aucune taille n'est donnée : presque tout paquet y compile, et un seul processus du compilateur prend jusqu'à 2,5 Gio. Les autres architectures gardent le minimum du catalogue
- Le code d'installation propre à s390x vit dans `script/install/S390x/` ; les scripts apt, dnf et zypper et `install_erplibre.sh` gardent une garde d'une ligne, et se comportent comme avant
- Un en-tête de compilation manquant arrête l'installation en quelques secondes et imprime la commande à lancer, au lieu que pyenv compile CPython pendant des minutes et échoue sur « zlib not available ». Sur s390x, la vérification nomme les paquets comme apt, dnf ou zypper les appellent, et les compilations de qpdf et PROJ disent quand la bibliothèque est absente et combien de temps elles prennent
- `make install_os` et `make install` nomment une architecture autre qu'amd64, arm64 et s390x et demandent s'il faut continuer, avant tout travail ; Entrée seule arrête. `EL_ALLOW_UNSUPPORTED_ARCH=1 make install_os` répond oui sans question, ce qu'exige une installation sans terminal. Le contrôle de compilation s390x ne tourne plus que sur s390x
- Le cœur d'Odoo 18 est OCB plus deux correctifs : les commandes `odoo-bin` d'ERPLibre viennent d'`erplibre_odoo_cli_base`, un module jamais installé qui ne porte qu'un paquet `cli/`. `./odoo_bin.sh db` prend des sous-commandes — `create`, `list`, `list-incompatible`, `version`, `load`, `dump`, `duplicate`, `rename`, `drop` — au lieu de drapeaux : `db --drop --database X` devient `db drop --if-exists X`, `--restore_image` devient `db load X --image NOM`. `--uninstall` devient `module uninstall`, `--install-theme` devient `theme apply`. `db drop`, et `-f` sur une base existante, vérifient le mot de passe maître lu dans `MASTER_PWD`. Un cœur qui porte encore les anciennes commandes, dont Odoo 12 à 15, voit la nouvelle syntaxe traduite
- Les manifestes d'Odoo 12 à 17 déclarent l'amont de chaque fork, le cœur d'Odoo suivant OCA/OCB comme en 18 ; `formio`, dont l'amont n'est plus publié, est son propre amont de 12 à 18. Les cœurs d'Odoo 12 à 15 sont clonés sur 20 commits, 16 à 18 gardent 10
- L'installation de TODO demande d'abord quoi installer, puis seulement « First system installation? » : pour une version d'Odoo, après les menus d'environnement et de type d'installation, si bien que revenir par `0` n'installe rien et que choisir une autre technologie n'amène plus la pile système d'Odoo. Une fois PyCharm ouvert pour indexer le projet, l'installation attend qu'il soit fermé — vérifié par `pgrep`, `c` passe outre —, car un PyCharm resté ouvert reprend son analyse à chaque fichier ajouté
- Un certificat local peut être signé par une autorité gardée dans un autre dossier (`ca_dir`) : plusieurs services partagent une autorité et un seul import dans le navigateur ; les certificats déjà émis là restent tels quels
- Odoo 18 tourne sur Python 3.12.16 au lieu de 3.12.10, six versions de sécurité plus tard : la clé de version, ses fichiers de dépendances, les cibles make, l'image Docker de base et le venv deviennent `odoo18.0_python3.12.16`, et son pyproject exige `>=3.12.16,<3.13` ; le verrou garde chaque paquet. Le venv d'outillage `.venv.erplibre` demande Python 3.15.2, où seule la majeure.mineure borne un interpréteur déjà présent : un venv resté en 3.14 fait refuser le démarrage à TODO, qui nomme `install_erplibre.sh`, lequel le rebâtit. Odoo 18 utilise Poetry 2.5.1 au lieu de 2.1.3, qui ne plafonne plus `virtualenv` sous la 21 qu'installe le verrou, si bien que `pip check` sort propre, et l'installation remplace le Poetry d'un venv existant dès que sa version diffère de `.poetry-version`. Le verrou d'Odoo 18 couvre aussi les dépôts extra, de 367 à 445 paquets, sans qu'aucune version ne baisse
- `image_db` est figé sur une révision au lieu de suivre `main` : un clone prend l'image de base d'Odoo 18 publiée (`odoo18.0_base.zip`), et non ce que `main` porte à ce moment
- `erplibre_info` est découpé en trois modules Odoo 18. `erplibre_info` garde les paramètres, le lanceur de scripts, la mécanique commune des runs et le redémarrage du serveur. `erplibre_info_git` porte les instantanés du code et la comparaison entre versions, et ne fait que lire git. `erplibre_info_git_fetch` porte tout ce qui écrit dans git — fetch et rebase, essai à sec et application du tirage, sauvegardes — et ne s'installe que sur un serveur Odoo lancé avec `--dev` ; chacune de ses actions est aussi refusée quand le serveur tourne sans `--dev`, en plus de l'option `erplibre_info_allow_server_actions`, du groupe Paramètres et du mode développeur. Les données existantes ne sont pas migrées : instantanés et runs repartent de zéro.
- Le code de l'image Docker, `/ERPLibre` et ses dépôts git, appartient au compte que nomme `ERPLIBRE_CODE_OWNER` à la construction, `odoo` par défaut, pour qu'`erplibre_info_git_fetch` puisse tirer depuis Odoo ; `root` construit une image qu'Odoo ne peut pas réécrire. Chaque étape qui y écrit tourne sous ce compte, sans `chown -R` qui recopierait l'arbre dans une couche de plus, et les paquets pip extra de l'entrée s'installent sous le propriétaire du venv. `script/git/repo_pull.py` vérifie avant le fetch que le dossier git de chaque clone est inscriptible, et le refuse sinon en nommant le chemin, le compte qui tourne et le propriétaire — dans un conteneur, il ajoute l'argument de construction à employer —, là où un fetch échouait sur `.git/objects` et `.git/FETCH_HEAD`
- Les images Docker d'Odoo 16 à 18 reposent sur Debian trixie au lieu de bookworm ; Odoo 12 à 15 restent sur bookworm, la dernière Debian qui ait une image Python 3.7 ou 3.8. Le Python d'une image vient toujours de l'image officielle, et non de Debian. Le wkhtmltopdf au Qt patché de bookworm s'installe sur trixie pour amd64 et arm64, chaque `.deb` vérifié contre son SHA-1 avant d'être installé, et imprime en-tête et pied de page dans un PDF. Le Dockerfile de base et celui de production ne reçoivent chacun que leurs propres arguments de construction, ce qui retire l'avertissement sur des arguments que personne ne lit, et les défauts de `docker/Dockerfile.prod.pkg` suivent Odoo 18 et ERPLibre 1.8.0 au lieu d'Odoo 16 et de la 1.6.0
- L'image Docker de production clone chaque dépôt sur le commit de son `freeze-revision` au lieu de la tête de sa branche : deux constructions du même commit d'ERPLibre portent le même code, et un projet sans gel arrête la construction avant toute synchronisation, en étant nommé. Les gels des fragments communs du manifeste que liste `conf/git_manifest*.csv` s'appliquent désormais aussi, là où seuls ceux de la version d'Odoo active le faisaient : `image_db` et les outils partagés y sont gelés, et le gel d'une autre version installée ou d'un manifeste privé reste ignoré. `script/docker/docker_build.sh --branches` construit une image de développement sur les branches, que TODO › Exécution › Docker / Podman › Construire l'image d'une version d'Odoo propose après les commits gelés, son défaut. L'image porte les modules extra, CybroOdoo et le reste du manifeste extra de la version, comme l'installation de production du TODO avec modules extra ; `--without_extra`, ou l'installation standard de ce menu, les laisse de côté ; `git_merge_repo_manifest.py --strict`, posé par `EL_FREEZE_STRICT=1`, refuse un projet sans gel, et une fusion en échec arrête désormais `update_manifest_local_dev.sh` avant `repo sync`
- Les manifestes d'Odoo 18 gèlent 110 dépôts sur la tête de leur branche, dont `queue_job`, de 18.0.2.0 à 18.0.4.1 : une base installée sur le gel précédent demande `-u` pour ses modules installés dont la version a changé, sans quoi Odoo fait tourner un code qui attend des colonnes que la base n'a pas, comme `queue_job_channel.capacity`.
- `docker-compose.yml`, que lance `make docker_run_daemon`, démarre l'image publiée d'ERPLibre 1.8.0 pour Odoo 18, `technolibre/erplibre:1.8.0_odoo_18.0_d3e5b5ad`, au lieu d'une image 1.6.0. Ses volumes sont gardés : une base créée par l'image 1.6.0 demande `-u` pour ses modules installés, comme pour le gel ci-dessus. `docker/docker-compose_odoo_18.0.yml` et sa variante selenium lancent encore l'image 1.6.0

- Les jeux Stream Deck, la galerie (`gallery_server.py`, `index.html`) et les sauvegardes vivent dans `script/stream_deck/games/` ; le programme du deck `game_tiler.py` devient `script/stream_deck/erplibre_streamdeck.py`. `DECK_PROGRAM=tiler` et `make streamdeck_tiler` gardent leur sens ; `make streamdeck_erplibre` s'y ajoute. Une galerie démarrée avant la mise à jour se relance, et GNOME Shell prend le nouveau chemin de la galerie à la prochaine ouverture de session. Les sauvegardes de djscratch se déplacent : `mv script/stream_deck/save/* script/stream_deck/games/save/`
- Les jeux Stream Deck et leur galerie passent dans leur propre dépôt, [streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), cloné dans `script/stream_deck/games/`, qu'ERPLibre ne suit plus. `manifest/git_manifest_streamdeck_game.xml`, listé dans `conf/git_manifest_streamdeck.csv`, dirige Google Repo sur sa branche `main` quand `script/stream_deck/games` existe ou avec `git_merge_repo_manifest.py --with_streamdeck`, comme pour le mobile, et `install_erplibre_home.sh --stream-deck` le clone quand il manque et amène un clone qu'il a fait au dernier commit de `main` à chaque exécution, en installant aussi le `requirements.txt` des jeux. Les sauvegardes des jeux quittent leur répertoire pour `$XDG_DATA_HOME/erplibre-home/streamdeck/save/` à la prochaine exécution. Tirer ce changement retire les fichiers des jeux d'un checkout et garde `script/stream_deck/games/save/` : `make erplibre_home_streamdeck_install` y clone les jeux, sauvegardes comprises. Avant `repo sync`, les scripts `update_manifest_*.sh` déplacent un clone ordinaire sans travail local vers `script/stream_deck/games.plain-clone-<date>/`, repo refusant les clones ordinaires, et gardent les sauvegardes. Sans les jeux, le menu des jeux de TODO, la galerie, `make streamdeck_<jeu>` et la passation (code 5) refusent en une ligne qui nomme cette commande ; le programme du deck et le service n'en dépendent pas
- La galerie des jeux Stream Deck n'écoute que sur 127.0.0.1, refuse un Host étranger et une requête d'un autre site, et ne sert que sa page ; ses routes qui agissent exigent l'en-tête `X-Stream-Deck-Gallery: 1`, que l'extension GNOME envoie désormais pour lancer un jeu (contrat des jeux 2.0, `script/stream_deck/games_contract`)
- Le réglage `GAMES=on|off` du fichier de réglages du deck active ou désactive la bibliothèque de jeux ; absent ou `on`, elle est active. Désactivée, le menu des jeux de TODO, la galerie, `make streamdeck_<jeu>` et le passage de relais refusent de lancer un jeu ; le programme du deck, le contrôleur et le service restent intacts
- Le sous-menu ERPLibre de l'extension est masqué tant qu'il ne liste aucun outil ; le programme du deck se lance depuis l'indicateur du périphérique
- L'entrée 8 du menu Déployer est désormais « Infrastructure d'appel », qui regroupe l'installation, `Préparer ntfy pour ERPLibre mobile`, la vérification et la désinstallation, et remplace l'entrée 7 « Installer le serveur de notifications NTFY » de la 1.8.0. Depuis la 1.8.0 : le proxy SOCKS prend l'entrée 4, si bien que SSH, QEMU/KVM et Proxmox VE passent de 4, 5 et 6 à 5, 6 et 7 ; les nouvelles entrées du cache QEMU et d'Asterisk sont 9 et 10 ; le VPN passe de 8 à 11

## Corrigé

- F7 (versions principales) les coche de nouveau dans le formulaire de déploiement Proxmox : il cochait les entrées par leur rang, alors que cette liste les identifie par système, version et architecture, et aucune VM n'était retenue
- L'action de mise à jour du suivi d'installation (`a`) atteint une installation de production : les parties git et Python allaient dans `~/git/erplibre`, absent d'une VM installée sous `/opt/erplibre`, et s'y arrêtaient. Le dossier est désormais lu dans le service erplibre

- Le programme du deck lance une action lente (export zenity, rechargement à chaud, application d'une disposition, connexion Bluetooth, commandes de session) hors du verrou : la touche affiche « … », le reste du deck reste utilisable, une touche du plugin occupé clignote en erreur, la touche 0 de sa page ramène à l'accueil, et le résultat clignote à la fin ; une tâche en échec est inscrite une fois au journal
- Les pages Son, Bluetooth, minuteurs et terminaux TODO, et la touche du micro de l'accueil, ne lancent plus de processus au rendu : elles lisent des caches que des sondages remplissent hors du verrou
- `settings.json`, `layouts.json` et `todo_terminals.json` sont remplacés de façon atomique : un plantage ou un disque plein ne laisse plus de fichier tronqué
- Une session Claude ou mpv dont le numéro de processus est maintenant porté par un processus plus récent est écartée, au lieu d'être gardée tant qu'un processus porte ce numéro
- Les pages de session Claude et mpv se rafraîchissent, et le deck revient à l'accueil quand leur session se termine
- L'étape du bureau du menu QEMU échoue, avec un code non nul et une ligne qui nomme le binaire absent, quand le bureau ne s'est pas installé : un environnement dnf qu'aucun miroir ne livrait finissait sur 0 et une VM sans `gnome-shell`. Sur AlmaLinux et Rocky Linux, elle active EPEL et CRB avant xrdp ; quand aucun dépôt activé ne porte xrdp, le bureau reste installé et une ligne dit que le RDP manque
- Le cache de téléchargement ne sert plus à une version de Fedora le paquet gardé pour une autre : un paquet que la nouvelle version n'a pas reconstruit garde son nom — `.fc41` dans l'arbre de la 42 — mais il est re-signé avec la clé de la nouvelle version, et les six derniers segments du chemin effaçaient le numéro de version, si bien que dnf rejetait la copie gardée sur sa somme auprès de chaque miroir. Les clés RPM gardent sept segments, à partir du numéro de version, ce qui réunit toujours les préfixes des miroirs. Un magasin rempli avant ce changement se rattrape par `--recle`, service arrêté
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
- NixOS apprend l'autorité du cache de téléchargement SANS reconstruire, et n'en est donc plus soustrait — ce qui lui fermait le déploiement hors ligne, le magasin étant alors la seule source et une VM exceptée n'ayant plus rien. Il n'a pas d'ancre de confiance par fichier et /etc est généré en lecture seule, quand une déclaration arriverait trop tard, la première reconstruction étant le premier téléchargement. L'autorité y est donc POINTÉE, consommateur par consommateur, par l'environnement — et l'environnement se perd à trois frontières que les quatre familles impératives ne rencontrent jamais. nix-daemon est activé par socket et ne voit aucune session : un fragment sous /run/systemd/system, un tmpfs inscriptible là où /etc ne l'est pas, l'atteint. sudo l'efface, et le nix de root parle droit au magasin local plutôt qu'au démon, téléchargeant lui-même : « Defaults env_keep » fait traverser les variables, visudo étant atteint par le profil du système, le PATH qu'y donne cloud-init ne portant aucun sudo. Et la session ssh s'ouvre une seconde avant que cloud-init n'écrive le faisceau, si bien que les exports vivent DANS l'attente de celui-ci plutôt qu'en tête de commande. Le faisceau concatène les autorités du système et celle du cache, donner la seconde seule ferait cesser d'approuver tout le reste. Vérifié amont COUPÉ sur une VM neuve : nix-shell réalise depuis le magasin ; et cache interceptant, une installation complète se termine sans un refus de certificat
- Odoo répond depuis l'extérieur d'une VM NixOS. Il écoutait sur 0.0.0.0:8069 et répondait en local, mais NixOS active un pare-feu par défaut là où aucune des quatre autres images cloud n'en active : l'hôte ne recevait rien — pas un refus, un silence jusqu'au délai — et le suivi déclarait Odoo absent sur une machine où il tournait. Mesuré depuis l'hôte : 000 après 12 s, puis 303 en 9 ms
- ERPLibre tourne comme service sur NixOS. L'installation finissait par écrire une unité dans `/etc/systemd/system`, généré depuis le store et monté en lecture seule : elle rendait 1 à sa dernière étape, après que le clone, le venv et un démarrage d'Odoo avaient tous réussi. L'unité est désormais déclarée par le module ; son interpréteur vient du store, `/bin` étant un montage FUSE d'envfs que systemd ne voit pas quand il résout l'exécutable ; et son PATH porte bash, dont l'absence arrêtait `run.sh` avant Odoo
- Ce qu'un système déclaratif doit déclarer, et que les quatre autres reçoivent gratuitement de leur image cloud : xmlsec1, sans lequel Odoo refuse d'installer auth_saml, module du chemin des addons ; parallel et shfmt, appelés par leur nom nu ; growpart, absent de tout le système alors que l'agrandissement du disque s'écrit « … || true » et rendait 0 sans rien agrandir ; et l'agent invité, qui venait de l'image et non du dépôt, le PATH de son unité manquant findmnt si bien que guest-exec mourait en 127 dès sa première ligne
- Le guide de connexion s'affiche sur NixOS. Le déploiement écrit `/etc/motd` partout et compte sur pam_motd pour le montrer — vrai des quatre images cloud, faux ici, où sshd rend « printmotd no » et où la pile PAM ne contient aucun pam_motd : le guide était écrit, complet, et personne ne le lisait. Il gagne aussi un bloc propre à NixOS, qui nomme le piège pour lequel il existe — `/etc/nixos/erplibre.nix` est réécrit par `make install_os`, et les déclarations qu'on y ajoute disparaissent sans un mot
- « make db_drop_all » n'annonce plus détruites des bases qui ne le sont pas. Il composait une commande parallel, jetait son code de retour et imprimait la liste ; le cas s'atteint dès que parallel manque du PATH, et l'opérateur passe à la suite en croyant ses bases parties
- Un miroir du cache de téléchargement refusé faute de place nomme son seuil et sa mesure. Il reprenait un champ que tout appelant ordinaire laisse à zéro — « moins de 0 o libres sur le disque » n'annonce aucun seuil et ne dit pas ce qui a été mesuré
- Une image téléchargée est vérifiée contre la somme que son éditeur publie, pour toute distribution qui en publie une et SANS le demander. La vérification existait sous un drapeau et pour Ubuntu seulement, si bien que les autres images arrivaient sans que rien ne les regarde. Six y entrent, relevées sur les dépôts plutôt que devinées : Debian publie du sha512 quand tout le reste est en sha256, les familles RHEL nomment le fichier « CHECKSUM », Rocky l'écrit en forme BSD, et Arch comme openSUSE posent une somme par image. Un fichier de sommes injoignable n'arrête plus un déploiement — c'est une panne de disponibilité — quand un écart arrête toujours tout et supprime l'image
- La locale qu'une VM déployée reçoit s'applique sur NixOS. cloud-init l'applique par locale-gen et update-locale, absents là-bas, et la VM gardait le défaut de la distribution — « fr_CA.UTF-8 » demandé, « en_US.UTF-8 » obtenu. Elle et le fuseau sont désormais déclarés par le module, et ni l'un ni l'autre n'est imposé à une NixOS qu'on avait déjà
- Le guide de connexion tient dans un terminal de 80 colonnes même sur une VM qui porte ses outils et un bureau, là où il en rendait 103 : le cadre débordait, le terminal repliait où il voulait, et l'alignement en deux colonnes — seule chose qui rend le guide lisible d'un coup d'œil — se perdait. La glose se replie désormais sous sa colonne, et passe sous sa commande quand celle-ci ne laisse plus de quoi écrire. C'est la mise en page qui porte la règle, non la longueur des textes, qui n'aurait tenu que jusqu'au prochain outil
- Une VM déployée hors ligne reçoit les variables du cache avant que son installation ne commence. « cloud-init status --wait » rend la main dès que cloud-init se déclare en erreur — un module accessoire y suffit — alors que son étape finale écrit encore l'autorité, `/etc/environment` et le fichier sudoers ; une session ouverte dans cette seconde-là vivait sans elles, et une installation lancée par sudo rejetait alors le certificat du cache. Le déploiement attend désormais l'unité cloud-final, et son seul état « activating », ce service étant un oneshot qui reste actif une fois fini
- Une métadonnée de dépôt qu'une distribution RPM nomme d'après l'empreinte de son contenu est servie du disque comme un paquet, et une demande de plage sur un fichier que le cache ne détient pas fait prendre le fichier entier en arrière-plan, une fois par clé. Un tel index de dizaines de mégaoctets était repris en entier à chaque installation — environ 110 Mo par VM sur un système de la famille RHEL — et dnf, qui prend ses métadonnées zchunk par plages, recevait un « 504 » l'amont coupé, aucune plage ne se gardant
- Une VM déployée hors ligne n'attend plus une synchronisation de l'heure qui ne peut pas venir. Une image qui active `systemd-time-wait-sync` retient `time-sync.target` jusqu'à la première réponse NTP, et l'étape finale de cloud-init est ordonnée après elle : sans serveur de temps joignable, cette étape ne démarrait jamais, ni les clés d'hôte ssh qu'elle génère, et la VM atteignait son invite de connexion sans jamais répondre en ssh
- Le cache de téléchargement ne reprend plus à l'amont un paquet qu'il détient déjà parce qu'un miroir le range sous un autre chemin. Un miroir préfixe le chemin à sa guise — « /rocky/10.2/… », « /mirror/rocky-linux/10.2/… », « /pub/archive/fedora/… » — et le chemin entier donnait deux clés pour les mêmes octets : sur un journal de 7099 noms livrés, 1124 vivaient sous plusieurs chemins et 3,18 Gio repartaient à l'amont pour rien. Seuls les six derniers segments comptent désormais, les segments vides tombant avec eux. Six est la plus petite borne sans collision : un chemin Debian en porte exactement six, si bien que cinq servirait le paquet d'Ubuntu pour celui de Debian, qui porte le même nom pour d'autres octets. Les paquets pacman s'arrêtent à quatre, leurs chemins étant plus courts que la borne commune, ce qui retire le préfixe du miroir et garde le nom du dépôt. Un magasin rempli avant ce changement se rattrape par `--recle`
- Une image gardée devenue périmée est reprise une fois au lieu d'arrêter le déploiement. Le répertoire « latest » d'une distribution avance à chaque version mineure et la somme publiée cesse de décrire l'image du disque, sans qu'un octet soit corrompu : la vérification la supprimait puis sortait, perdant une campagne entière — trois VM — pour une péremption qu'un seul téléchargement répare. Un second écart porte sur des octets fraîchement téléchargés, arrête tout et supprime l'image ; appelée sans liste de miroirs, et pour des sommes injoignables, rien ne change
- `long_test/qemu_cache.py` ne fait plus échouer une campagne où le cache a tout servi. Une URL n'est « déjà vue » que si la première VM en a obtenu les octets : un même paquet vit sous deux chemins selon le miroir, et la première VM peut recevoir « 504 » sur l'un — amont jugé muet — puis être servie du disque par l'autre, si bien que rien n'était rangé sous le premier chemin et que le téléchargement honnête de la seconde y était compté en faute. Un statut absent vaut livré, les journaux d'avant ne l'écrivant pas toujours, et la ligne des fichiers neufs nomme ses deux causes au lieu d'imputer à Arch quelle que soit la distribution mesurée
- Un téléchargement d'image coupé se reprend sur le même miroir, trois essais, par un `Range` qui demande la suite, au lieu de jeter ce qu'il a reçu : une image de VM pèse un demi-gigaoctet, et un `.part` tronqué renvoyait le lecteur à un `curl -C -` tapé à la main. Un serveur qui ignore le Range rend le fichier entier, et le transfert repart alors de zéro plutôt que de doubler les octets déjà là
- Les variables de certificat du cache ne désignent un faisceau que s'il existe. Une Fedora récente n'a pas `/etc/pki/tls/certs/ca-bundle.crt`, et viser un chemin absent faisait refuser à pip TOUT téléchargement, y compris ce qui n'a rien à voir avec le cache. Aucun trouvé n'écrit aucune variable, et pip garde son propre jeu de certificats
- `make version` nomme les deux Python, celui d'Odoo et celui de l'outillage. Un libellé nu laissait croire que le dépôt n'en a qu'un, et le chiffre affiché n'était pas celui du venv dans lequel on travaille
- `make` ne lance plus un `.venv.erplibre` bâti sur une autre machine, comme un checkout monté par le réseau, qui mourait sur « No module named 'encodings' ». `install.sh` lit la version de l'interpréteur en exécutant du code : `python -V` répond avant le chargement de la bibliothèque standard, et se portait donc garant d'un interpréteur incapable de démarrer. Un tel venv est désormais signalé comme bâti ailleurs, avec la commande qui le rebâtit
- Dependabot n'ouvre plus de demandes de fusion sur les requirements figés d'Odoo 12 à 17 : ses mises à jour de sécurité lisent `requirement/` comme un répertoire à part, que les exclusions ne couvraient pas
- `poetry_update.py` s'arrête sur un `pyproject.toml` absent en nommant la commande qui le crée, `make switch_odoo_XX` pour la version active, et propose de la lancer puis de se relancer quand il tourne dans un terminal
- `poetry_update.py` fait tourner Poetry dans le venv Odoo même depuis un shell sous `.venv.erplibre`, dont le Python le faisait échouer sur « InvalidCurrentPythonVersionError »
- `poetry_update.py` écarte les requirements et manifestes sous un répertoire `doc`, `docs`, `example` ou `examples` : un fichier d'exemple déclarant un `>=` lâche ne déplace plus une dépendance pour tout l'environnement
- `docker_build.sh --odoo_<N>` bâtit la version demandée. `--odoo_15` produisait une image d'Odoo 18 sous le nom de la 15 : le catalogue se lisait avec `python` nu, absent de Debian sans `python-is-python3`, et la base de l'image figeait `ODOO_EXEC_BIN` sur `odoo18.0`. Une version inconnue arrête désormais la construction
- Bâtir un commit absent du dépôt public s'arrête d'emblée et nomme le `git push` à taper, au lieu d'échouer au bout du clone sur « reference is not a tree ». Un dépôt injoignable ne bloque pas la construction
- L'image de production compile pykcs11 avec l'alias `PyInt_FromLong` que `install_locally.sh` donne déjà à l'hôte : SWIG 4.3 l'a retiré, et les images d'Odoo 14, 15 et 17 s'arrêtaient à `poetry install`. Un test échoue si les deux définitions divergent
- Les Dockerfile écrivent `ENV clé=valeur` : buildkit ne signale plus le format hérité à chaque construction
- Les tests unitaires n'atteignent plus l'hôte qui les lance : un vrai `sudo virsh` qui demandait un mot de passe là où libvirt exige root, `ssh` et `~/.ssh/config` lus par les tests du formulaire Proxmox, l'UUID d'un vrai domaine écrit dans un rapport de test long, un `input()` qui bloquait dès que la suite partait d'un terminal, et le script d'installation Proxmox joué contre les outils Debian, le nom et l'adresse de l'hôte. Trois tests de l'écran de composition cessent aussi de tourner dix fois chacun
- Un test unitaire qui remplace le `PATH` par les répertoires système doit doubler `sudo` dans la fonction qui le bâtit, et un test de garde refuse celui qui ne le fait pas : sans quoi le script testé atteignait le vrai `sudo`, qui demandait un mot de passe ou s'exécutait en root sur un hôte en `NOPASSWD`
- La suite unitaire passe dans un clone neuf, sans `.odoo-version` : les tests de migration fixent la version, et les deux qui vérifient la lecture du fichier se disent ignorés
- `make doc_markdown` s'arrête au bord de ce dépôt. Il régénérait aussi la documentation de `mobile/`, un dépôt distinct doté de sa propre génération, et effaçait ainsi une section écrite directement dans l'un de ses fichiers générés
- La suite unitaire passe sur un poste sans adb, sans les addons de Google Repo ni l'état d'une démonstration SMS, sur un poste qui est lui-même invité de libvirt et sur un poste sans cloud-init : les tests SMS et modem bâtissent un checkout jetable et fournissent des réponses `ip` fixées au lieu de lire la machine, et n'écrivent plus de compte de softphone dans `private/`. Les tests d'appairage USB n'envoient plus de vraies commandes `pm grant` et `am broadcast` à un téléphone branché, le test du compte courriel clique sur le bouton OAuth une fois son défilement arrêté, et non en pleine animation, et le test de la console du modem ne perd plus un clic rapide sur ⟳ dans l'effet d'appui du bouton — tous deux échouaient ou passaient selon la charge du poste
- La fin du journal d'un fichier en échec, telle que l'affiche le lanceur de tests unitaires, finit sur le verdict d'unittest : les impressions du test, vidées à la sortie, enterraient l'erreur sous elles
- Restaurer une image d'`image_db/` mesure la place qu'elle demande, décompressée et quota compris, et extrait dans le cache utilisateur quand `/tmp` n'y suffit pas, au lieu de s'arrêter sur « Disk quota exceeded »
- Une restauration qui laisse une base vide — psql rend zéro même quand toutes les instructions ont échoué — est refusée, et un cache ou une source vides le sont avant la suppression de la cible, au lieu d'être recopiés sans un mot par le clone
- Créer un prospect CRM avec un courriel, depuis le formulaire du site par exemple, ne lève plus ModuleNotFoundError sur Odoo 18 : `dnsq`, que flanker importe pour vérifier le MX, est installé
- Le venv d'Odoo 18 n'imprime plus une AttributeError d'extendable-pydantic à chaque démarrage de Python : pydantic reste sous 2.14, qui retire la fonction interne qu'il lit
- `poetry_update.py` évalue les marqueurs `python_version` des dépendances de manifest et lit les plages comme `>=1.7.1,<2.9.0` : l'épingle d'un manifest n'écrase plus celle d'ERPLibre, et une plage n'arrête plus le script. `oauthlib<4` et `pylint<4.1` gardent la résolution d'Odoo 18 possible
- L'installateur de ntfy fonctionne par ssh et converge sur une installation plus ancienne : son unité systemd peut écrire `/var/lib/ntfy`, où vit la base d'accès, et cette base appartient à `ntfy` ; chaque appel `ntfy user` porte `--config` et ne voit aucune variable `NTFY_*` sauf le mot de passe, passé par l'environnement et jamais par argv ; https écoute sur `NTFY_HTTPS_PORT` (8443 par défaut) au lieu d'un 443 fixe ; sur Arch, le paquet des dépôts passe toujours en premier ; `NTFY_NON_INTERACTIVE=1` empêche dpkg de poser une question sur une configuration modifiée et, quand les dépôts d'Arch n'ont pas ntfy, installe le binaire officiel au lieu d'appeler un assistant AUR ; la dernière ligne est `@@ACTIVE ntfy <état>`, avec une sortie non nulle quand le service n'est pas actif ; une configuration de paquet faite seulement de commentaires est mise de côté en `server.yml.origine` au lieu d'arrêter l'installation
- Odoo 18 s'installe sur s390x avec chaque système supporté : le Rust 1.95 ou plus récent qu'exige orjson vient de rustup quand celui de la distribution est plus ancien, avec apt, dnf et zypper pareillement, sans fausse erreur à côté du Rust de la distribution
- pynacl et pykcs11 compilent de nouveau là où ils compilent : l'alias SWIG passe d'un `-D` dont les parenthèses cassaient les Makefile d'autotools à un en-tête forcé par `-include`
- Le swap fonctionne sur une racine btrfs, comme sur Fedora et openSUSE, dans un sous-volume NOCOW dédié ; un swap actif est laissé tel quel, et quand la mémoire suffit déjà, l'étape le dit au lieu d'accuser le disque
- `poetry install` n'échoue plus au hasard sur un `_virtualenv.py` supprimé : les paquets que Poetry amène dans le venv sont d'abord alignés sur `poetry.lock`, dépendances de leurs nouvelles versions comprises, et un venv resté incomplet est réparé
- Une installation dont `poetry install` a échoué reprend à la relance : la synchronisation repo en arrière-plan s'arrête en entier et garde son journal, et `--install_dev` exige `odoo-bin` et une installation réussie enregistrée. Une première installation n'est plus annoncée comme reprise
- QEMU : les VM Debian installées par debian-installer font confiance à l'autorité du cache de téléchargement, et leur clone n'échoue plus sur TLS ; les VM Fedora s390x n'affichent plus un systemd-firstboot en échec à chaque connexion ; un déploiement prend ou génère la clé SSH avant de créer la moindre VM, au lieu de sonder 20 minutes puis d'échouer sur « Permission denied » ; la note d'émulation ne paraît que sous émulation ; le journal du cache nomme un amont injoignable au lieu de se lire comme une panne du cache
- Le suivi d'installation termine en trois minutes environ l'installation d'une VM qui ne répond plus : ses sessions SSH envoient des keepalive au lieu d'attendre sur une connexion morte le délai TCP du système, plus de deux heures
- Le venv d'Odoo 18 reçoit `websocket-client`, sans lequel chaque test navigateur lève SkipTest : le pyproject 18.0 le déclarait sous une table `[poetry.group.dev.dependencies]`, privée de son préfixe `tool.`, que Poetry ignore sans un mot. C'est désormais une dépendance principale, épinglée à 1.8.0 dans le requirements d'ERPLibre pour que `poetry_update.py` la garde
- Une installation neuve n'échoue plus dans `repo init` : les scripts `update_manifest_*` lui donnent une branche, celle qui est extraite ou une branche contenant un HEAD détaché, jamais un commit, que `repo init` ne sait pas résoudre sur un espace de travail vide ; le script de production passe aussi son manifeste
- Le mode dev de Docker synchronise le checkout monté par `update_manifest_local_dev.sh`, met `odoo-bin` dans le `PATH`, et démarre Odoo sur une configuration qui porte l'`addons_path` du checkout ; il lançait `repo init` sur un manifeste qui n'existe plus et démarrait de toute façon sur la configuration de l'image
- Le serveur git local sert le commit gelé : un clone détaché sur son gel ne voit plus extraire sa branche locale homonyme quand celle-ci est sur un autre commit, et le commit est poussé sous le nom de la branche à la place
- Une installation QEMU n'est annoncée réussie qu'une fois Odoo en service : la commande distante se connecte à PostgreSQL sous `db_user`, puis attend jusqu'à 600 s `/web/login`, et échoue avec la fin du journal sur une connexion refusée, des 5xx répétés ou un service arrêté ou qui boucle
- Odoo 12 compile de nouveau ses bundles SCSS : `libsass` 0.17.0 remplace 0.12.3, qui n'a pas de wheel pour Python 3.7 et, compilé par un GCC récent, perdait un symbole à l'import
- TODO lit le port d'Odoo dans `xmlrpc_port` comme dans `http_port` : tuer par port ne plante plus sur un `config.conf` écrit par `generate_config.sh`, et la mise en route HTTP frappe au port configuré
- QEMU : des VM déployées ensemble téléchargent une seule fois leur image de base commune ; les autres attendent et la réutilisent, au lieu de la tirer chacune en entier dans le même `.part` et d'échouer sur « No such file or directory » quand la première le renomme. Une image en cache périmée n'est de même reprise qu'une fois, et non une fois par VM. Une erreur réseau passagère (délai dépassé, connexion coupée, HTTP 5xx ou 429) est réessayée sur le même miroir après 5 s puis 10 s, en reprenant le fichier partiel
- Les installeurs Linux créent le rôle PostgreSQL par `sudo runuser -u postgres` et s'arrêtent quand cela échoue, au lieu de masquer l'erreur : `su - postgres` est refusé sous Arch, dont le compte postgres est verrouillé, et l'installation se déclarait alors réussie quand Odoo répondait « Internal Server Error » à chaque page, faute de rôle. `sudo -u postgres` demanderait le mot de passe de postgres sous le `targetpw` par défaut d'openSUSE
- Chaque installation de paquet depuis TODO rafraîchit d'abord les index — `apt-get update`, `zypper refresh`, rien pour dnf — et n'installe rien si le rafraîchissement échoue, au lieu d'échouer sur les index vides d'un système neuf. Sous Arch, c'est `pacman -Syu`, une mise à jour complète du système : annoncée, elle ne part que sur un oui tapé
- Choisir la production dans l'installation de TODO extrait désormais les commits gelés d'une version déjà installée : l'installation ne trouvait rien à faire et sautait le repo sync, laissant les dépôts sur leurs branches. Un manifeste local dont le mode diffère de celui demandé exige le sync, dans les deux sens
- Les installeurs Linux promeuvent un rôle PostgreSQL existant qui n'est pas superutilisateur, au lieu de le tenir pour prêt et de laisser Odoo échouer plus tard à créer sa base ; une promotion refusée arrête l'installation avec la commande à taper
- La restauration de base du suivi d'installation vérifie que la VM est toujours celle déployée (UUID, rangée non effacée) avant la confirmation et avant de lancer, et relit dans libvirt l'adresse d'une VM locale : sur une session rouverte plus tard, elle pouvait atteindre une autre machine qui avait repris l'adresse. La relance détecte toute la première installation encore en cours, pas seulement `make` ; une recréation refusée n'arrête plus les lanceurs ; un second suivi n'adopte plus une entrée périmée
- QEMU : une image de base périmée est remplacée sur place une fois la nouvelle complète et vérifiée, au lieu d'être effacée d'abord sous une VM qui la convertit ; un verrou d'un autre utilisateur verrouille quand même, en lecture seule ; un échec TLS ou une URL invalide n'est plus retenté comme passager
- Dans les formulaires de déploiement QEMU et Proxmox, F4 et les boutons de rangée pressés pendant une annulation ou une reprise modifient la VM sur laquelle ils ont été pressés, retrouvée par sa clé, et non celle qui occupe cette rangée dans le plan restauré
- `script/poetry/poetry_update.py` remet le pyproject et sort en 1 quand `poetry add` est refusé, là où il sortait en 0 en laissant le pyproject vidé de ses dépendances, le verrou ne lui correspondant plus
- Installer une version d'Odoo déjà marquée installée réinstalle quand son venv manque ou porte un autre Poetry que celui déclaré : l'installation répondait « Nothing to do » après un changement de Python ou de Poetry, gardait l'ancien venv et laissait `.poetry-version` en arrière
- Le venv d'outillage de l'image Docker installe `click` : `script/git/repo_state.py` l'importe, si bien que chaque instantané d'`erplibre_info_git` échouait dans le conteneur. La construction importe désormais `repo_state` et `repo_pull` une fois les dépôts synchronisés, là où les modules `erplibre_info` sont clonés, et s'arrête quand un requis manque
- **TODO › Exécution › Mise à jour › Mise à jour Poetry** garde `./poetry.lock` en lien vers le verrou de `requirement/` : elle effaçait les deux verrous, Poetry écrivait alors un vrai fichier à la racine, et les deux divergeaient jusqu'au prochain changement de version. Elle propose ensuite d'installer le nouveau verrou dans le venv d'Odoo, ou affiche `EL_PHASE=poetry ./script/install/install_locally.sh` à lancer plus tard, et ne propose rien quand la mise à jour a échoué
- `script/docker/docker_build.sh` s'arrête quand `docker_update_version.py` échoue, là où sa vérification lisait le code d'une affectation de variable et ne se déclenchait jamais
- Le contrôle du filestore après la restauration d'une base n'annonce plus la moitié d'une sauvegarde d'Odoo 18 comme jamais arrivée : la sauvegarde porte, sous `filestore/checklist/`, un marqueur vide par pièce jointe pour le ramasse-miettes du filestore d'Odoo, que le contrôle comptait comme fichiers attendus. Une restauration complète de l'image de base d'Odoo 18 annonce désormais tous ses fichiers en place ; un filestore imbriqué ou réellement manquant est toujours signalé


## Retiré

- La dépendance `sshconf`, déclarée et installée partout et importée nulle part
- L'image Docker de base n'installe plus vim, qui dépend à la version près de vim-common, commun à toutes les architectures : un correctif de sécurité publié avant le binaire d'une architecture y arrêtait toute la construction. gdebi-core part aussi, apt installant lui-même le `.deb` de wkhtmltopdf

- `TODO › Déployer › Installer le serveur de notifications NTFY`, qui installait ntfy sur cette machine seulement ; `TODO › Déployer › Infrastructure d'appel` l'installe sur cette machine ou par ssh, avec coturn

## Sécurité

- Une clé d'API et un jeton Bearer sont caviardés eux aussi avant qu'une commande soit affichée, journalisée ou réimprimée : `OPENAI_API_KEY=` partait en clair, et un jeton d'en-tête échappait par construction, ne portant ni nom d'option ni nom de variable
- En suivant une redirection, le cache ne transmet plus les identifiants du client (Authorization, Cookie, Proxy-Authorization) à un autre hôte
- Odoo 18 installe `idna` 3.20 au lieu de la 3.6 qu'épinglent ses propres requirements, touchée par CVE-2024-3651
- Odoo 18 installe `requests` 2.34.2 au lieu du 2.31.0 qu'épinglent ses propres requirements, touché par CVE-2024-35195, CVE-2024-47081 et CVE-2026-25645
- Le miroir git du cache QEMU ne clone plus qu'en `http` et `https` : un client pouvait nommer un dépôt `ssh://` ou `git://` dans sa requête et faire se connecter le cache, avec les clés de son compte de service, à un hôte de son choix. Les dépôts servis en HTTPS sont mis en miroir comme avant ; le binaire annonce 0.2.17
- L'installateur de ntfy ne laisse plus de canal d'alerte ouvert : l'accès est refusé par défaut (`auth-default-access: deny-all`), là où le défaut de ntfy laisse quiconque apprend un nom de sujet le lire et y publier, et une configuration déjà en place sans cette directive est refusée au lieu d'être gardée en silence. Le compte d'administration est créé avant le démarrage du service, sa base sous `/var/lib` où le compte `ntfy` peut écrire, et le bandeau final ne dit que ce qui a été vérifié. `NTFY_PUBLIC=1` rétablit un serveur volontairement public
- Odoo 18 épingle la première version qui corrige les CVE connues des versions qu'épinglent ses propres requirements, chaque CVE notée à côté de son épingle : `urllib3` 2.8.0, `werkzeug` 3.1.9, `jinja2` 3.1.6, `lxml` 6.1.3 avec `lxml-html-clean` 0.4.6, `python-ldap` 3.4.8, `certifi` 2026.10.23, `pypdf` 6.21.4 et `pillow` 13.0.0. PyPDF2 2.x, qu'Odoo 18 importe avant `pypdf`, garde CVE-2023-36464, qu'aucune version de PyPDF2 ne corrige ; `python-jose` et `ecdsa` ont elles aussi des CVE sans version corrigée
- Poetry ignore, à la résolution, toute version publiée depuis moins de 7 jours (`solver.min-release-age` dans `poetry.toml`) : une version malveillante d'un paquet légitime est en général retirée en un à trois jours. `poetry install` suit le verrou et n'est jamais retenu. `make poetry_update` exempte les paquets épinglés par `==` dans `requirement/requirements.<version>.txt` ; `POETRY_SOLVER_MIN_RELEASE_AGE_EXCLUDE=nom make poetry_update` en laisse passer un autre, comme l'explique `doc/POETRY.fr.md`
- La passerelle SIP (`script/erplibre_sip_go`) se compile avec `golang.org/x/crypto` 0.58.0 au lieu de 0.48.0, qui portait 30 avis ; 0.58.0 ne laisse que celui de `x/crypto/openpgp`, un paquet sans correctif que la passerelle n'importe pas
- Le verrou d'Odoo 18 épingle ses dépendances transitives à la première version qui corrige leurs CVE connues, de 27 paquets visés par des avis à 9 : `aiohttp` 3.14.4, `anyio` 4.14.2, `authlib` 1.9.1, `cbor2` 5.9.0, `filelock` 4.2.1, `h2` 4.4.1, `hpack` 4.2.0, `joserfc` 1.7.6, `markdownify` 0.14.1, `msgpack` 1.2.3, `multidict` 6.9.1, `pyasn1` 0.6.5, `soupsieve` 2.9.0, `starlette` 1.3.1, `tornado` 6.6, `virtualenv` 21.14.13, `webob` 1.8.11 et `zeep` 4.3.3. `bokeh` reste en 3.6.3 pour le JS de `web_widget_bokeh_chart` ; l'avis vise le serveur bokeh, qu'Odoo ne lance jamais
- Les dépendances d'outillage posent des planchers aux versions corrigées, parce que pip ne met jamais à jour un venv existant : `pillow` 13.0.0 au lieu d'une 12.3.0 qui portait 40 CVE, `virtualenv` 21.14.13, `GitPython` 3.2.1, `filelock` 4.2.1, `tornado` 6.6, `certifi` 2026.10.18 et `nbconvert` 7.17.2. Le venv de Transform data passe lui aussi à Pillow 13.0.0
- Odoo 18 et le venv d'outillage formatent avec black 26.10.1 au lieu de 24.8.0, installé depuis PyPI plutôt que git : 24.8.0 portait CVE-2026-32274, une écriture de fichier arbitraire par le nom de son fichier de cache
- Odoo 18 installe `oauthlib` 4.0.0, qui corrige CVE-2026-49264, CVE-2026-49265, CVE-2026-49272 et CVE-2026-118669. `tweepy`, qui exige encore `oauthlib<4` dans sa 4.17.0, est écarté par `requirement/ignore_requirements.odoo18.0_python3.12.16.txt` : le module CybroAddons `recruitment_twitter` n'est plus installable
- Odoo 18 n'installe plus Js2Py, dont l'évasion de bac à sable (CVE-2024-28397) n'a pas de correctif et qui ne tourne plus sous Python 3.12. `code_generator_demo_converter_js` lit le JavaScript téléchargé avec tree-sitter : il prend dans l'arbre syntaxique la valeur affectée à la variable et refuse tout ce qui n'est pas un littéral, là où Js2Py traduisait le fichier en Python et l'importait, exécutant le code distant
- Odoo 18 installe `paramiko` 5.1.0 au lieu de 3.5.1, qui acceptait les signatures RSA en SHA-1 (CVE-2026-44405). Les clés DSA ne sont plus prises en charge, ni l'échange de clés en SHA-1, ni GSSAPI : un serveur SSH antérieur à OpenSSH 7.2 n'est plus joignable. `pysftp`, abandonné et qui importe la prise en charge DSA, disparaît : `auto_backup` se connecte directement par paramiko et refuse un serveur dont la clé diffère de la clé d'hôte configurée, port compris. `storage_backend_sftp` et `cetmix_tower_server` n'essaient plus les clés DSA. Le verrou d'Odoo 18 ne garde que 5 paquets visés par des avis sans correctif utilisable, au lieu de 9
- La clé du dépôt de PostgreSQL dans les images Docker ne vaut que pour ce dépôt (`signed-by`), au lieu de valoir pour toutes les sources APT de l'image

- L'installateur de ntfy lance `ntfy user` sous le compte `ntfy` quand il existe et ne change plus en root le propriétaire de la base d'accès : un `chown` root suivait un lien symbolique que le compte `ntfy` pouvait poser dans `/var/lib/ntfy`
- La configuration de coturn gérée par l'outil refuse par défaut de relayer vers les adresses privées, de bouclage, lien-local, partagées (CGNAT) et locales uniques (`denied-peer-ip`), si bien que le relais n'atteint pas le réseau de l'hôte ; seul `TURN_ALLOW_PRIVATE=1` le lève, que le mode développement d'`Infrastructure d'appel` passe et que l'installateur annonce
- La configuration de coturn s'écrit par un fichier `mktemp` dans son propre dossier, et un `turnserver.conf` qui est un lien symbolique est refusé avant toute installation de paquet
- Les scripts root d'`Infrastructure d'appel` et de `Préparer ntfy pour ERPLibre mobile` ne voyagent plus en argv, que tout compte local lit : sur cette machine, sudo lance un fichier temporaire 0600 ; par ssh, le script est d'abord déposé par l'entrée standard dans un dossier 0700 du compte de connexion, puis lancé par sudo, si bien qu'une clé TLS privée fournie n'apparaît plus dans la liste des processus. Un passage root par ssh ouvre désormais deux connexions
- Le mot de passe de contrôle de coturn est tiré sur l'hôte et jamais envoyé ; le diff montré avant d'adopter une configuration en masque les valeurs secrètes (mots de passe, jetons, clés, chaînes de connexion) des deux côtés, le fichier écrit les gardant
- Le mode production d'`Infrastructure d'appel` ne passe jamais `TURN_ALLOW_PRIVATE` à l'installateur de coturn : le relais continue de refuser les adresses privées, de bouclage, lien-local, partagées et locales uniques, et la vérification le prouve par une vraie permission de relais vers une adresse privée, qui doit être refusée. ntfy n'écoute que sur 127.0.0.1, et le site de nginx n'accepte que TLS 1.2 et 1.3
- Le fichier d'identifiants d'un greffon DNS, une clé d'API, ne voyage jamais en argv et ne s'affiche jamais : il passe dans le corps du script root, arrive root 0600 dans un dossier 0700, et l'installateur de certbot le refuse s'il est un lien symbolique ou porte une permission de groupe ou d'autres ; la désinstallation le retire quoi qu'il soit arrivé au reste
- Le crochet de déploiement vérifie l'unité et le chemin de configuration de coturn qu'il lit dans l'état avant de s'en servir, refuse un fichier ou un dossier de certificat qui est un lien symbolique, et écrit les copies de coturn par des fichiers `mktemp` renommés en place, à root et au groupe que l'installateur a donné à ce dossier, 0640. La désinstallation le retire avant les services, si bien qu'un renouvellement pendant la désinstallation ne peut pas signaler coturn
- Le site nginx et le minuteur certbot de l'outil portent sa marque en première ligne, et un fichier à leur nom qui ne la porte pas est refusé plutôt que remplacé. Le webroot ACME vit hors de `/var/lib/erplibre-call`, qui reste 0750. Un passage qui échoue après avoir remis en place un fichier de renouvellement mis de côté le remet de côté, si bien que le minuteur ne reprend jamais le renouvellement d'un certificat que la désinstallation a gardé


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