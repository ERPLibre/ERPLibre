<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# VPN — five open tunnels, secrets in a KeePassXC vault

`vpn.py` brings up, tears down and diagnoses a VPN tunnel. One driver per
technology, five of them, all free software.

The split is the whole design: what is *not* secret (host, user, routes, MTU)
lives in readable JSON configuration; the pre-shared keys and the passwords
live in a KeePassXC `.kdbx` vault. A profile can therefore be shown, compared
and shared without handing over the means to bring the tunnel up.

<!-- [fr] -->
# VPN — cinq tunnels ouverts, secrets dans un coffre KeePassXC

`vpn.py` monte, démonte et diagnostique un tunnel VPN. Un pilote par
technologie, cinq en tout, tous libres.

Le partage est tout le dispositif : ce qui n'est PAS secret (hôte,
utilisateur, routes, MTU) vit dans une configuration JSON lisible ; les clés
pré-partagées et les mots de passe vivent dans un coffre KeePassXC `.kdbx`. Un
profil peut donc être montré, comparé, partagé — sans donner de quoi monter le
tunnel.

<!-- [en] -->
## Which one to pick

| Driver | Pick it when | Secrets in the vault |
|--------|--------------|----------------------|
| `l2tp_ipsec` | the far side imposes it: a router, a firewall, Windows RRAS | PSK + PPP password |
| `wireguard` | you control both ends — fastest, simplest | private key (+ optional PSK) |
| `openvpn` | the site handed you a `.ovpn` file | password, if the file needs one |
| `openconnect` | Cisco AnyConnect, Pulse, GlobalProtect, Fortinet appliances | password |
| `sshuttle` | all you have is SSH access — nothing to install on the far side | none: SSH keys do the work |

<!-- [fr] -->
## Lequel choisir

| Pilote | À prendre quand | Secrets dans le coffre |
|--------|-----------------|------------------------|
| `l2tp_ipsec` | le site l'impose : un routeur, un pare-feu, Windows RRAS | PSK + mot de passe PPP |
| `wireguard` | on tient les deux bouts — le plus rapide, le plus simple | clé privée (+ PSK facultative) |
| `openvpn` | le site a fourni un fichier `.ovpn` | mot de passe, si le fichier en veut un |
| `openconnect` | boîtiers Cisco AnyConnect, Pulse, GlobalProtect, Fortinet | mot de passe |
| `sshuttle` | on n'a qu'un accès SSH — rien à installer en face | aucun : les clés SSH suffisent |

<!-- [en] -->
## Commands

<!-- [fr] -->
## Commandes

<!-- [common] -->
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

<!-- [en] -->
Everything is also reachable from the CLI: **TODO › Execute › Deployment ›
VPN**, and from **TODO › Execute › Network › VPN** — a tunnel gets looked for
in both places. The menu is where profiles are created and secrets are typed
in; `vpn.py` is what the menu runs. Connecting from the menu shows the plan
first and asks before running it.

Run it as **yourself, not under sudo**: the vault lives in your home and its
master password is yours to type. Each privileged step calls `sudo` on its
own, and `--dry-run` shows every one of them without running any.

<!-- [fr] -->
Tout est aussi accessible depuis le CLI : **TODO › Execute › Déploiement ›
VPN**, et depuis **TODO › Execute › Réseau › VPN** — un tunnel se cherche aux
deux endroits. Le menu est là pour créer les profils et saisir les secrets ;
`vpn.py` est ce que le menu lance. Se connecter depuis le menu montre d'abord
le plan, et demande avant de l'exécuter.

À lancer en tant qu'**utilisateur, pas sous sudo** : le coffre est dans votre
home et son mot de passe maître est le vôtre. Chaque étape privilégiée appelle
`sudo` séparément, et `--dry-run` les montre toutes sans en exécuter aucune.

<!-- [en] -->
## Where things live

| Path | Content |
|------|---------|
| `private/todo/todo_override_private.json` | your profiles — gitignored, 0600 |
| `script/todo/todo.json` | the `vpn` section, empty: profiles shared by a team can go here |
| your `.kdbx` vault | one entry per profile, `ERPLibre VPN / <profile>` |
| `/dev/shm/erplibre-vpn/<profile>/` | 0700 root — **the secrets**, in tmpfs, erased on `down` |
| `/run/erplibre-vpn/<profile>.*` | non-secret state (chosen interface, pid, log), readable without sudo |
| `/etc/ipsec.conf`, `/etc/ipsec.secrets` | L2TP only: a marked block, removed on `down` |

<!-- [fr] -->
## Où vivent les choses

| Chemin | Contenu |
|--------|---------|
| `private/todo/todo_override_private.json` | vos profils — gitignored, 0600 |
| `script/todo/todo.json` | la section `vpn`, vide : les profils partagés par une équipe peuvent y aller |
| votre coffre `.kdbx` | une entrée par profil, `ERPLibre VPN / <profil>` |
| `/dev/shm/erplibre-vpn/<profil>/` | 0700 root — **les secrets**, en tmpfs, effacés au `down` |
| `/run/erplibre-vpn/<profil>.*` | l'état non secret (interface retenue, pid, journal), lisible sans sudo |
| `/etc/ipsec.conf`, `/etc/ipsec.secrets` | L2TP seulement : un bloc marqué, retiré au `down` |

<!-- [en] -->
## The three security rules

1. **No secret in an argument.** `/proc/<pid>/cmdline` is readable by every
   user of the machine. Secrets travel on standard input only; a single place
   (`runner.py`) holds that rule, and a unit test replays the plan of **every**
   driver and fails if a secret ever reaches a command line.
2. **No secret on persistent storage.** The files a technology insists on are
   written 0600 into tmpfs and erased on `down`. Two drivers need none at all:
   OpenConnect passes the password on standard input (`--passwd-on-stdin`), and
   sshuttle has no secret to begin with. One residual, stated rather than
   hidden: while an L2TP tunnel is up, root can read the pppd options file.
   pppd takes a password from a file or nothing.
3. **The master password is written nowhere.** Leave `kdbx.password` empty; it
   is asked once per session. Only the vault *path* is stored, in the single
   gitignored file. The CLI says so when it finds a master password in the
   configuration.

The L2TP PSK reaches strongSwan **hex-encoded** (`PSK 0x…`): same bytes, and
no question of escaping a `"` or a `\` inside a pre-shared key.

<!-- [fr] -->
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

<!-- [en] -->
## What each driver settles for you

**L2TP/IPsec** — three stages, and all three are needed for an interface:
IPsec in **transport** mode protects UDP 1701, L2TP opens a session inside it,
PPP authenticates. Six pitfalls are handled here, all six found by connecting
to a real concentrator:

- `charon { install_routes = no }`, otherwise charon installs a route that
  captures the L2TP traffic — the classic *"the SA is established, ppp0 never
  appears"*.
- An **AppArmor** rule. AppArmor confines charon by path and `/dev/shm` is not
  in its profile, so charon is denied the secrets file by the kernel and fails
  three stages later on *"no shared key found"* — with the PSK sitting there,
  correct. Only `journalctl -k | grep DENIED` says so. The rule goes in the
  `local/` file Debian and Ubuntu provide for exactly this.
- **`rightid=%any`**. A gateway announces itself by its IP even when `right`
  is a name; without this, strongSwan refuses: *"IDir '203.0.113.5' does not
  match to 'vpn.example.com'"*.
- **A wait for the connection to load.** `ipsec start` returns before the
  starter has pushed the connections; an immediate `ipsec up` fails on *"no
  match"* — on a perfectly valid configuration, the most misleading error of
  the sequence.
- **The direction of authentication.** `require chap` / `require
  authentication` (xl2tpd) and `require-mschap-v2` (pppd) all mean *require
  the PEER to authenticate to us*. A client must not: the server refuses, and
  pppd tears the link down with *"LCP terminated by peer (peer refused to
  authenticate)"*. What a client wants is `refuse-pap` and `refuse-eap` —
  which speak about **us**.
- A `/32` survival route to the server (in all-traffic mode the ESP packets
  would enter the tunnel they carry), and `resolvectl`, because
  systemd-resolved ignores `/etc/ppp/resolv.conf`.

One packaging note that costs an hour if missed: without the **openssl**
plugin (`libstrongswan-standard-plugins`), charon advertises 3DES, the
concentrator picks it — often the only cipher it knows — and the negotiation
dies on *"ENCRYPTION_ALGORITHM 3DES_CBC not supported!"*. The installer ships
it.

**WireGuard** — it has no session, so `wg-quick up` succeeds even with a wrong
peer key or an unreachable endpoint. Nothing says no, because nobody is there
to say it. This driver therefore **waits for a handshake** before calling the
tunnel up. Routes come from `AllowedIPs` and belong to `wg-quick`; the driver
does not double its work. No `DNS =` line either: wg-quick hands that to
`resolvconf`, missing from many systemd-resolved installs, and the whole
configuration fails when it is.

**OpenVPN** — it starts from the `.ovpn` the site gave you; this driver does
not invent one. Two things that are not obvious: `--cd`, because a `.ovpn`
references its neighbours relatively; and option order, because what follows
`--config` overrides the file — a bare `auth-user-pass` inside would otherwise
wait for a keystroke that never comes, the daemon being detached. Split tunnel
is asked for with `--route-nopull`, which also drops the pushed DNS; the driver
says so when it takes it.

**OpenConnect** — `--non-inter` is deliberate in password mode. Without it an
unknown server certificate raises a question, and openconnect would read the
answer from the standard input the password arrives on. With it, openconnect
refuses at once **and** prints the `--servercert sha256:…` line to paste into
the profile's `oc_servercert`. Routes belong to the server, through
`vpnc-script`; the profile can add to them, not replace them.

Set **`oc_sso`** when the concentrator authenticates through a **web form**
(SAML / SSO — Azure AD, Okta, Duo). There is then no password to send, and
Cisco's own client needs a screen for its embedded WebKit browser — often
with `WEBKIT_DISABLE_DMABUF_RENDERER=1` for it to render at all; its CLI
cannot do this flow. openconnect can, with no screen on the client machine:
measured in its library, it listens on **local port 29786** and waits for the
browser's redirect after launching `--external-browser` with the login URL.
On a server that "browser" is a plain `echo`, so the URL is printed for you to
open in **your own** browser — bring the redirect back with

```bash
ssh -L 29786:localhost:29786 <the client machine>
```

before opening it. The password never leaves your own workstation. Both
timeouts differ on purpose: two minutes for a password, five for a human
walking through an identity provider.

**sshuttle** — no interface at all: it redirects through the firewall. Every
interface and routing check is therefore silent for it, and the **witness
address** is the only judge — this driver is the reason the `probe` field
exists. It also insists on being run by *you*: it calls sudo itself, for the
firewall only. Running it under sudo would open the SSH session as root, with
root's keys.

<!-- [fr] -->
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

<!-- [en] -->
## Diagnosing

`diagnose` chains the checks and names the failing stage, lowest first, so
that the first false line is the cause and not a consequence: what the
**kernel** exposes · packages present · the technology's own check (IPsec SA,
WireGuard handshake, daemon alive, OpenVPN initialisation) · interface and
addresses · each declared route · the witness address that only answers
through the tunnel · the last lines of the relevant journal. Set `probe` in
the profile to an address reachable only through the tunnel — without it,
*"it works"* stays an impression, and for sshuttle there is nothing else to
go on.

The kernel stage catches a failure no configuration can fix. Upgrading the
kernel package replaces `/lib/modules/<version>` with the new version's:
the running kernel keeps the modules already loaded and can load no other.
IPsec then becomes unavailable on a kernel that supports it, charon aborts
at initialisation on a missing `kernel-ipsec`, and the symptom surfaces three
stages higher as a connection never loaded. `diagnose` and `up` name the
version whose modules are gone and offer the only remedy — a reboot. It is
offered, never done: nothing is applied on a dry run, nor without a terminal
to answer.

<!-- [fr] -->
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

<!-- [en] -->
## Adding a driver

`drivers/base.py` states the contract *and* carries everything true of all
technologies: directory layout, state kept between processes, routes,
systemd-resolved, the standard status checks. A new driver declares what is
its own — packages, secrets, profile fields, the form the menu unrolls, the
sequence up and down — and executes nothing: it asks a `Runner`, which either
runs or merely shows. Registering it is one line in `drivers/__init__.py`, and
`test_vpn_drivers.py` picks it up from the registry: the no-secret-on-a-command
-line rule applies to it whether or not anyone thought about it.

<!-- [fr] -->
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
