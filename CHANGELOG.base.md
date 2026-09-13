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

<!-- [fr] -->

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

<!-- [en] -->
## Changed
<!-- [fr] -->
## Modifié
<!-- [en] -->

- The comment hygiene check reads Go comments, not only `#` ones: `//` outside a string, the raw string between backticks, and `/* … */` blocks
- Debian and Ubuntu `by-hash` index files are served from disk, their name being the digest of their content; `…/releases/latest/download/…` is no longer pinned to the first version seen
- An upstream that refuses or drops connections is remembered for 20 s: a request with a stored answer is served at once instead of waiting its connect timeout, which made up most of an offline install's time; a request with nothing stored still tries upstream. A git mirror skips its refresh while its forge is unreachable
- Mirror prefetch runs under the cache's service account, never as root

<!-- [fr] -->

- Le contrôle d'hygiène des commentaires lit le Go, et non les seuls `#` : `//` hors d'une chaîne, la chaîne brute entre accents graves, et les blocs `/* … */`
- Les index `by-hash` de Debian et d'Ubuntu sont servis du disque, leur nom étant l'empreinte de leur contenu ; `…/releases/latest/download/…` n'est plus figé sur la première version vue
- Un amont qui refuse ou ignore les connexions est retenu 20 s : une requête qui a une réponse gardée est servie aussitôt au lieu d'attendre son délai d'établissement, qui faisait l'essentiel du temps d'une installation hors ligne ; une requête sans rien en réserve tente toujours l'amont. Un miroir git saute son rafraîchissement tant que sa forge est injoignable
- Le pré-remplissage des miroirs tourne sous le compte du service du cache, jamais en root

<!-- [en] -->
## Fixed
<!-- [fr] -->
## Corrigé
<!-- [en] -->

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
- The refusal to copy the cache to another machine names the gesture that lifts it, and that gesture is not entry 1 — entry 1 installs the cache HERE, so following it reinstalled the host that already had one while the target stayed empty. Three situations were reported as a single « no cache installed »: an ssh link that never ran the probe, a target carrying no cache, and a target whose cache lacks its service account. Each has its own message now, and the missing-cache one lists the steps to run ON the target, the two ways past an installer that reads the « default » libvirt network included — start libvirt, or name the bridge, a stopped libvirt making it die on a network that exists. The guide carries the same section

<!-- [fr] -->

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
- Le refus d'emporter le cache sur une autre machine nomme le geste qui le lève, et ce geste n'est pas l'entrée 1 — elle pose le cache ICI, si bien que la suivre faisait réinstaller l'hôte qui en avait déjà un pendant que l'arrivée restait sans rien. Trois situations étaient rendues par un seul « pas de cache » : un lien ssh qui n'a jamais exécuté la sonde, une arrivée sans cache, une arrivée dont le cache n'a pas son compte de service. Chacune a désormais son message, et celle du cache absent énumère les gestes à faire SUR l'arrivée, avec les deux issues d'un installateur qui lit le réseau libvirt « default » — lever libvirt, ou nommer le pont, un libvirt arrêté le faisant mourir sur un réseau qui existe. Le guide porte la même section

<!-- [en] -->
## Security
<!-- [fr] -->
## Sécurité
<!-- [en] -->

- Following a redirect, the cache no longer forwards the client's credentials (Authorization, Cookie, Proxy-Authorization) to another host

<!-- [fr] -->

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
