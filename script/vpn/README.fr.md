
# VPN — cinq tunnels ouverts, secrets dans un coffre KeePassXC

`vpn.py` monte, démonte et diagnostique un tunnel VPN. Un pilote par
technologie, cinq en tout, tous libres.

Le partage est tout le dispositif : ce qui n'est PAS secret (hôte,
utilisateur, routes, MTU) vit dans une configuration JSON lisible ; les clés
pré-partagées et les mots de passe vivent dans un coffre KeePassXC `.kdbx`. Un
profil peut donc être montré, comparé, partagé — sans donner de quoi monter le
tunnel.

## Lequel choisir

| Pilote | À prendre quand | Secrets dans le coffre |
|--------|-----------------|------------------------|
| `l2tp_ipsec` | le site l'impose : un routeur, un pare-feu, Windows RRAS | PSK + mot de passe PPP |
| `wireguard` | on tient les deux bouts — le plus rapide, le plus simple | clé privée (+ PSK facultative) |
| `openvpn` | le site a fourni un fichier `.ovpn` | mot de passe, si le fichier en veut un |
| `openconnect` | boîtiers Cisco AnyConnect, Pulse, GlobalProtect, Fortinet | mot de passe |
| `sshuttle` | on n'a qu'un accès SSH — rien à installer en face | aucun : les clés SSH suffisent |

## Commandes

```bash
./script/vpn/vpn.py check                          # ce que la machine sait faire
sudo bash script/install/install_vpn.sh wireguard  # ou : tous, sans argument
./script/vpn/vpn.py list
./script/vpn/vpn.py up       --profile acme --dry-run
./script/vpn/vpn.py up       --profile acme
./script/vpn/vpn.py status   --profile acme
./script/vpn/vpn.py diagnose --profile acme
./script/vpn/vpn.py down     --profile acme
```

Tout est aussi accessible depuis le CLI : **TODO › Execute › Déploiement ›
VPN**, et depuis **TODO › Execute › Réseau › VPN** — un tunnel se cherche aux
deux endroits. Le menu est là pour créer les profils et saisir les secrets ;
`vpn.py` est ce que le menu lance. Se connecter depuis le menu montre d'abord
le plan, et demande avant de l'exécuter.

À lancer en tant qu'**utilisateur, pas sous sudo** : le coffre est dans votre
home et son mot de passe maître est le vôtre. Chaque étape privilégiée appelle
`sudo` séparément, et `--dry-run` les montre toutes sans en exécuter aucune.

## Où vivent les choses

| Chemin | Contenu |
|--------|---------|
| `private/todo/todo_override_private.json` | vos profils — gitignored, 0600 |
| `script/todo/todo.json` | la section `vpn`, vide : les profils partagés par une équipe peuvent y aller |
| votre coffre `.kdbx` | une entrée par profil, `ERPLibre VPN / <profil>` |
| `/dev/shm/erplibre-vpn/<profil>/` | 0700 root — **les secrets**, en tmpfs, effacés au `down` |
| `/run/erplibre-vpn/<profil>.*` | l'état non secret (interface retenue, pid, journal), lisible sans sudo |
| `/etc/ipsec.conf`, `/etc/ipsec.secrets` | L2TP seulement : un bloc marqué, retiré au `down` |

## Préréglages de site

Un préréglage est un **profil partiel** : tout ce qu'un établissement publie
et qui est le même pour tout le monde — passerelle, protocole, groupe
d'authentification, port, limites du concentrateur. Il ne porte **ni
identifiant ni secret**, et c'est précisément ce qui lui permet de se
distribuer. Créer un profil à partir d'un préréglage ne laisse à taper que
l'identité, et rien d'autre.

`VPN › Créer un profil à partir d'un préréglage de site` les liste, puis
déroule le formulaire ordinaire pré-rempli : une réponse vide garde la valeur
du préréglage.

Les préréglages sont lus dans ces répertoires, dans l'ordre :

| Chemin | Usage |
|--------|-------|
| `conf/vpn_presets/` | livré avec le dépôt — des gabarits seulement, passerelles inventées, **rien d'identifiant** |
| `private/vpn/presets/` | ignoré par git : le point de montage d'un dépôt privé de préréglages réels |
| tout répertoire de `vpn_preset_paths` | un dépôt privé cloné ailleurs |

Le **plus tardif gagne** sur un même identifiant. C'est ce qui permet à un
site de corriger un gabarit livré — une passerelle qui a déménagé, un groupe
renommé — sans modifier un fichier suivi par git, donc sans conflit au
prochain `git pull`.

Un fichier `.json` porte un préréglage (objet) ou plusieurs (liste). Outre les
champs de profil, trois clés décrivent le préréglage lui-même : `preset`
(identifiant, minuscules, chiffres, `-` ou `_`), `label` et un `hint`
facultatif. Un fichier illisible est signalé et sauté — un préréglage fautif
ne doit pas rendre les autres inatteignables.

## Un VPN SSL (AnyConnect), distribution par distribution

Le pilote `openconnect` parle AnyConnect (Cisco), Pulse/Juniper,
GlobalProtect, Fortinet, F5 et Array. Une commande installe son client :

```bash
sudo bash script/install/install_vpn.sh openconnect
./.venv.erplibre/bin/python script/vpn/vpn.py check --driver openconnect
```

| Distribution | Paquets | `vpnc-script` |
|--------------|---------|---------------|
| Debian, Ubuntu | `openconnect vpnc-scripts` | `/usr/share/vpnc-scripts/vpnc-script` |
| Arch, Manjaro | `openconnect` (tire `vpnc-scripts`) | `/usr/share/vpnc-scripts/vpnc-script` |
| Fedora, RHEL, Rocky, Alma | `openconnect` (tire `vpnc-script`) | `/etc/vpnc/vpnc-script` |
| openSUSE | `openconnect` (tire `vpnc-script`) | `/etc/vpnc/vpnc-script` |

`vpnc-script` est le seul prérequis qui **n'est pas** un binaire du `PATH` :
l'installateur cherche donc le fichier lui-même et nomme le paquet à installer
quand il manque. Sans lui, openconnect démarre, la session s'ouvre, et
l'interface tun n'apparaît jamais — une panne trois étages au-dessus du paquet
absent, sur un symptôme qui ne l'accuse pas.

Deux champs décident de presque tout le reste. `oc_authgroup` est le **groupe
d'authentification** que le site demande de choisir ; une faute de frappe
dedans revient en « identifiants refusés », sans que rien ne désigne le
groupe. `oc_password_len` déclare que le concentrateur **ne compare que les N
premiers caractères** du mot de passe — certains le font, reste d'une limite
d'annuaire. Zéro veut dire aucune limite. Le champ ne tronque jamais : il le
dit avant qu'on dépose le secret, et il compare les longueurs au montage. N'en
déposer que ces N caractères.

À la première connexion, openconnect refuse un certificat serveur non épinglé
et **imprime** la ligne `--servercert sha256:…` à recopier dans
`oc_servercert`. Ce refus est la première étape attendue, pas une panne.

## Les deux « groupes » d'une passerelle AnyConnect

Un même concentrateur héberge plusieurs services, et deux mécanismes tout à
fait différents servent à en désigner un. Les confondre ne donne pas une
erreur de syntaxe : cela donne **le formulaire d'un autre service**, donc un
refus sur des identifiants justes, sans que rien ne désigne le groupe.

| Champ du profil | openconnect | Ce que c'est |
|-----------------|-------------|--------------|
| `oc_usergroup` | `--usergroup=X` | le **chemin d'URL** : `--usergroup=X` et `https://hôte/X` sont la même chose |
| `oc_authgroup` | `--authgroup=X` | une valeur à choisir dans un **menu déroulant** que le serveur présente |

Un site qui remet un profil `.xml` désigne son service par le chemin ; un
site qui décrit une liste à choisir dans une capture d'écran désigne le sien
par le menu déroulant.

Dans un fichier `AnyConnectProfile` de Cisco, `<UserGroup>` est le chemin et
`<HostName>` n'est qu'un libellé d'affichage — malgré son nom, ce n'est pas
un nom d'hôte ; c'est `<HostAddress>` qui l'est. `VPN › Importer un profil
AnyConnect (.xml)` lit ces trois balises et écrit des préréglages dans
`private/vpn/presets/`, pour que le champ qui décide vraiment du service
joint ne soit jamais retapé.

## SSO / SAML : ce qu'openconnect sait faire, et ce qu'il ne sait pas

Quand une passerelle authentifie par un fournisseur d'identité (Okta, Azure
AD, Duo), il n'y a pas de mot de passe à envoyer — il faut compléter une page
web. Cisco l'annonce de **deux** façons différentes, et une seule des deux
fonctionne depuis un CLI nu :

| Le serveur annonce | openconnect exige | Marche avec un paquet de distribution |
|--------------------|-------------------|---------------------------------------|
| `single-sign-on-external-browser` | `--external-browser=<cmd>` | **oui** — remplir `oc_external_browser` |
| `sso-v2` (navigateur intégré) | une webview compilée (libwebkit2gtk) | **non** — Debian, Ubuntu, Fedora et Arch la compilent sans |

C'est la passerelle qui choisit, groupe de connexion par groupe de
connexion. Quand elle réclame le navigateur intégré et qu'openconnect n'a
pas de webview, il s'arrête sur :

```
Please complete the authentication process in the AnyConnect Login window.
No SSO handler
Failed to complete authentication
```

`--external-browser` n'y change **rien** : openconnect ne prend ce chemin
que si le serveur a annoncé la méthode « navigateur externe ». Laquelle
une passerelle veut se lit sans envoyer aucun secret :

```bash
openconnect --protocol=anyconnect --usergroup=<GROUPE> \
    --authenticate --dump-http-traffic <passerelle> 2>&1 \
    | grep -E 'sso-v2|external-browser|No SSO handler'
```

### Déléguer le formulaire web, garder le tunnel

Pour une passerelle qui exige le navigateur intégré, renseigner
`oc_sso_helper` avec un exécutable `openconnect-sso`. Le pilote partage
alors le travail :

| Étape | Qui | Sous quel compte | Ce qui circule |
|-------|-----|------------------|----------------|
| SAML / MFA dans un vrai navigateur | le greffon, `--authenticate json` | **vous** (il lui faut votre affichage et votre trousseau) | rend `{host, cookie, fingerprint}` |
| montage du tunnel | ce pilote, `--cookie-on-stdin` | root, par `sudo` | le cookie, par l'entrée standard seulement |

Ce partage est tout le dispositif. Le greffon ne fait *que* la danse SAML ;
le **profil** reste la source de vérité pour le nom d'interface, les routes
ajoutées, les fichiers d'état et le diagnostic. Un tunnel ouvert par le
greffon lui-même s'appellerait `tun0`, ne laisserait rien dans `/run`, et
`status`, `diagnose` et `down` ne le verraient pas.

Deux détails font échouer le cookie si on les néglige, et le pilote s'en
charge : l'**identité annoncée** doit être la même aux deux étapes
(`oc_ac_version` va au greffon *et* à openconnect — un cookie délivré à une
version de client est refusé à une autre), et l'**empreinte** que rend le
greffon prime sur `oc_servercert`, parce que c'est celle contre laquelle il
a authentifié. Beaucoup de ces passerelles présentent une chaîne que le
magasin du système ne valide pas (`signer not found`), et `--non-inter` la
refuserait sans épinglage.

Le cookie ne touche aucun fichier : il vit dans une variable, part par
l'entrée standard, et est masqué de tout affichage dès qu'il existe. Sur une
machine sans accélération exploitable — une machine virtuelle, typiquement —
le Chromium embarqué se rabat sur Vulkan et la fenêtre meurt au milieu de
l'authentification ; le pilote force donc le rendu logiciel, sauf si ces
variables sont déjà posées.

Le chemin retenu se décide en UN endroit, et se lit dans cet ordre :

| `oc_sso` | `oc_sso_helper` resolves | Path |
|---|---|---|
| yes | yes | helper authenticates, this driver mounts |
| yes | declared but not executable | **refused, and says so** — never a silent fallback |
| yes | no | `--external-browser`, openconnect alone |
| no | — | password from the vault |

Un greffon déclaré qui ne peut pas s'exécuter est une erreur, pas une
invitation à prendre l'autre chemin : se replier sans bruit ferait échouer le
montage sur `No SSO handler`, trois étages au-dessus de la vraie cause — un
chemin fautif.

`vpn.py status` et `diagnose` portent une ligne `greffon SSO` : le chemin
résolu, `absent`, ou `sans objet` quand le profil authentifie par mot de
passe.

## Les trois règles de sécurité

1. **Aucun secret en argument.** `/proc/<pid>/cmdline` est lisible par tout
   utilisateur de la machine. Les secrets ne passent que par l'entrée
   standard ; un seul endroit (`runner.py`) porte cette règle, et un test
   unitaire rejoue le plan de **chaque** pilote et échoue si un secret atteint
   une ligne de commande.
2. **Aucun secret sur un disque persistant.** Les fichiers qu'une technologie
   exige sont écrits en 0600 dans un tmpfs et effacés au `down`. Deux pilotes
   n'en ont aucun : OpenConnect passe le mot de passe par l'entrée standard
   (`--passwd-on-stdin`), et sshuttle n'a pas de secret du tout. Un résiduel,
   dit plutôt que caché : tant qu'un tunnel L2TP est monté, root peut lire le
   fichier d'options pppd. pppd prend un mot de passe dans un fichier, ou pas
   du tout.
3. **Le mot de passe maître ne s'écrit nulle part.** Laisser `kdbx.password`
   vide ; il est demandé une fois par session. Seul le *chemin* du coffre est
   retenu, dans le seul fichier gitignored. Le CLI le signale s'il trouve un
   mot de passe maître dans la configuration.

Le PSK L2TP arrive à strongSwan **en hexadécimal** (`PSK 0x…`) : mêmes octets,
et plus aucune question d'échappement d'un `"` ou d'un `\` dans une clé
pré-partagée.

## Ce que chaque pilote règle pour vous

**L2TP/IPsec** — trois étages, et il faut les trois pour avoir une interface :
IPsec en mode **transport** protège l'UDP 1701, L2TP ouvre une session dedans,
PPP authentifie. Six pièges réglés ici, les six trouvés en montant un tunnel
vers un vrai concentrateur :

- `charon { install_routes = no }`, sinon charon pose une route qui capte le
  trafic L2TP — le classique *« la SA est établie, ppp0 n'apparaît pas »*.
- Une règle **AppArmor**. AppArmor confine charon par chemin et `/dev/shm`
  n'est pas dans son profil : le noyau lui refuse le fichier de secrets, et
  l'échec ressort trois étages plus loin en *« no shared key found »* — avec
  le PSK bien là, bien formé. Seul `journalctl -k | grep DENIED` le dit. La
  règle va dans le fichier `local/` que Debian et Ubuntu prévoient pour ça.
- **`rightid=%any`**. Une passerelle s'annonce par son IP même quand `right`
  est un nom ; sans cela, strongSwan refuse : *« IDir '203.0.113.5' does not
  match to 'vpn.exemple.com' »*.
- **Une attente du chargement de la connexion.** `ipsec start` rend la main
  avant que le starter ait poussé les connexions ; un `ipsec up` immédiat
  échoue sur *« no match »* — sur une configuration parfaitement valide,
  l'erreur la plus trompeuse de la séquence.
- **Le sens de l'authentification.** `require chap` / `require
  authentication` (xl2tpd) et `require-mschap-v2` (pppd) veulent tous dire
  *exiger que le PAIR s'authentifie auprès de nous*. Un client ne doit pas :
  le serveur refuse, et pppd coupe la liaison — *« LCP terminated by peer
  (peer refused to authenticate) »*. Ce qu'un client veut, c'est `refuse-pap`
  et `refuse-eap`, qui parlent de **nous**.
- Une route de survie `/32` vers le serveur (en mode « tout le trafic », les
  paquets ESP entreraient dans le tunnel qu'ils portent), et `resolvectl`,
  parce que systemd-resolved ignore `/etc/ppp/resolv.conf`.

Une note d'empaquetage qui coûte une heure si on la manque : sans le greffon
**openssl** (`libstrongswan-standard-plugins`), charon annonce 3DES, le
concentrateur le choisit — c'est souvent le seul qu'il connaisse — et la
négociation meurt sur *« ENCRYPTION_ALGORITHM 3DES_CBC not supported! »*.
L'installateur le livre.

**WireGuard** — il n'a pas de session, donc `wg-quick up` réussit même avec
une clé de pair fausse ou un endpoint injoignable. Rien ne dit non, parce
qu'il n'y a personne pour le dire. Ce pilote **attend donc une poignée de
main** avant de déclarer le tunnel monté. Les routes viennent d'`AllowedIPs`
et appartiennent à `wg-quick` ; le pilote ne double pas son travail. Pas de
ligne `DNS =` non plus : wg-quick la confie à `resolvconf`, absent de beaucoup
d'installations systemd-resolved, et c'est la configuration entière qui échoue
alors.

**OpenVPN** — il part du `.ovpn` que le site a fourni ; ce pilote n'en
fabrique pas. Deux choses qu'on aurait tort de croire évidentes : `--cd`,
parce qu'un `.ovpn` référence ses voisins en relatif ; et l'ordre des options,
parce que ce qui suit `--config` l'emporte sur le fichier — un
`auth-user-pass` nu dedans ferait sinon attendre une saisie qui ne viendra
jamais, le démon étant détaché. Le tunnel scindé se demande par
`--route-nopull`, qui écarte aussi le DNS poussé ; le pilote le dit quand il
le prend.

**OpenConnect** — `--non-inter` est voulu en mode mot de passe. Sans lui, un
certificat serveur inconnu déclenche une question, et openconnect la lirait
sur l'entrée standard par laquelle arrive le mot de passe. Avec lui,
openconnect refuse tout de suite **et** imprime la ligne
`--servercert sha256:…` à recopier dans le champ `oc_servercert` du profil.
Les routes appartiennent au serveur, via `vpnc-script` ; le profil peut en
ajouter, pas les remplacer.

Cocher **`oc_sso`** quand le concentrateur authentifie par un **formulaire
web** (SAML / SSO — Azure AD, Okta, Duo). Il n'y a alors aucun mot de passe à
envoyer, et le client de Cisco réclame un écran pour son navigateur WebKit
embarqué — souvent avec `WEBKIT_DISABLE_DMABUF_RENDERER=1` pour qu'il
s'affiche ; son CLI, lui, ne sait pas faire cet échange. openconnect le fait
sans écran sur la machine cliente : mesuré dans sa bibliothèque, il écoute sur
le **port local 29786** et attend la redirection du navigateur, après avoir
lancé `--external-browser` avec l'URL de connexion. Sur un serveur, ce
« navigateur » est un simple `echo` : l'URL s'affiche, et on l'ouvre dans
**son propre** navigateur — en faisant revenir la redirection par

```bash
ssh -L 29786:localhost:29786 <la machine cliente>
```

avant de l'ouvrir. Le mot de passe ne quitte jamais votre poste. Les deux
délais diffèrent exprès : deux minutes pour un mot de passe, cinq pour un
humain qui traverse un fournisseur d'identité.

**sshuttle** — aucune interface : il détourne par le pare-feu. Toutes les
vérifications d'interface et de routage sont donc muettes pour lui, et
l'**adresse témoin** est le seul juge — ce pilote est la raison d'être du
champ `probe`. Il exige aussi d'être lancé par *vous* : il appelle sudo
lui-même, pour le pare-feu seulement. Le lancer sous sudo ferait ouvrir la
session SSH par root, avec les clés de root.

## Diagnostiquer

`diagnose` enchaîne les vérifications et nomme l'étage fautif, du plus bas au
plus haut pour que la première ligne fausse soit la cause et non une
conséquence : ce que le **noyau** expose · paquets présents · la vérification
propre à la technologie (SA IPsec, poignée de main WireGuard, démon vivant,
initialisation OpenVPN) · interface et adresses · chaque route déclarée ·
l'adresse témoin qui ne répond qu'à travers le tunnel · les dernières lignes
du journal concerné. Mettre `probe` dans le profil à une adresse joignable
seulement par le tunnel — sans elle, *« ça marche »* reste une impression, et
pour sshuttle il n'y a rien d'autre.

L'étage du noyau attrape une panne qu'aucune configuration ne rattrape.
Mettre à jour le paquet du noyau remplace `/lib/modules/<version>` par celle
de la version neuve : le noyau qui tourne garde les modules déjà chargés et
ne peut plus en charger aucun autre. L'IPsec devient alors indisponible sur
un noyau qui le prend en charge, charon abandonne à l'initialisation sur un
`kernel-ipsec` manquant, et le symptôme ressort trois étages plus haut en
connexion jamais chargée. `diagnose` et `up` nomment la version dont les
modules ont disparu et proposent le seul remède : redémarrer. C'est proposé,
jamais fait : rien n'est appliqué à blanc, ni sans terminal pour répondre.

## Ajouter un pilote

`drivers/base.py` énonce le contrat *et* porte tout ce qui est vrai de toutes
les technologies : disposition des répertoires, état gardé entre deux
processus, routes, systemd-resolved, vérifications d'état habituelles. Un
pilote nouveau déclare ce qui lui est propre — paquets, secrets, champs de
profil, formulaire que le menu déroule, séquence de montée et de descente — et
n'exécute rien : il demande à un `Runner`, qui exécute ou se contente de
montrer. L'enregistrer tient en une ligne dans `drivers/__init__.py`, et
`test_vpn_drivers.py` le prend depuis le registre : la règle « aucun secret
dans une ligne de commande » s'applique à lui, que quelqu'un y ait pensé ou
non.