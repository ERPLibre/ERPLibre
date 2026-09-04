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
## Site presets

A preset is a **partial profile**: everything an institution publishes and
that is the same for everybody — gateway, protocol, authentication group,
port, concentrator limits. It carries **no username and no secret**, which is
exactly what lets it be handed around. Creating a profile from one leaves the
identity to type, and nothing else.

`VPN › Create a profile from a site preset` lists them, then runs the ordinary
form pre-filled: an empty answer keeps the preset value.

Presets are read from these directories, in order:

| Path | Use |
|------|-----|
| `conf/vpn_presets/` | shipped with the repository — templates only, invented gateways, **nothing identifying** |
| `private/vpn/presets/` | git-ignored: the mount point for a private repository of real site presets |
| any directory in `vpn_preset_paths` | a private repository cloned somewhere else |

The **latest wins** on the same identifier. That is what lets a site correct a
shipped template — a gateway that moved, a group that was renamed — without
editing a git-tracked file, so without a conflict on the next `git pull`.

One `.json` file holds one preset (an object) or several (a list). Beyond the
profile fields, three keys describe the preset itself: `preset` (identifier,
lowercase, digits, `-` or `_`), `label` and an optional `hint`. An unreadable
file is reported and skipped — a broken preset must not make the others
unreachable.

<!-- [fr] -->
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

<!-- [en] -->
## An SSL VPN (AnyConnect), distribution by distribution

The `openconnect` driver speaks AnyConnect (Cisco), Pulse/Juniper,
GlobalProtect, Fortinet, F5 and Array. One command installs its client:

<!-- [fr] -->
## Un VPN SSL (AnyConnect), distribution par distribution

Le pilote `openconnect` parle AnyConnect (Cisco), Pulse/Juniper,
GlobalProtect, Fortinet, F5 et Array. Une commande installe son client :

<!-- [common] -->
```bash
sudo bash script/install/install_vpn.sh openconnect
./.venv.erplibre/bin/python script/vpn/vpn.py check --driver openconnect
```

<!-- [en] -->
| Distribution | Packages | `vpnc-script` |
|--------------|----------|---------------|
| Debian, Ubuntu | `openconnect vpnc-scripts` | `/usr/share/vpnc-scripts/vpnc-script` |
| Arch, Manjaro | `openconnect` (pulls `vpnc-scripts`) | `/usr/share/vpnc-scripts/vpnc-script` |
| Fedora, RHEL, Rocky, Alma | `openconnect` (pulls `vpnc-script`) | `/etc/vpnc/vpnc-script` |
| openSUSE | `openconnect` (pulls `vpnc-script`) | `/etc/vpnc/vpnc-script` |

`vpnc-script` is the one prerequisite that is **not** a binary on the `PATH`,
so the installer looks for the file itself and names the package to install
when it is missing. Without it openconnect starts, the session opens, and the
tun interface never appears — a failure three stages above the missing
package, on a symptom that does not accuse it.

Two fields decide almost everything else. `oc_authgroup` is the
**authentication group** the site tells you to select; a typo in it comes back
as “login failed”, with nothing pointing at the group. `oc_password_len`
declares that the concentrator **compares only the first N characters** of the
password — some do, a legacy directory limit. Zero means no limit. The field
never truncates: it says so before you store the secret, and it compares
lengths when the tunnel comes up. Store just those N characters.

On the first connection openconnect refuses an unpinned server certificate and
**prints** the `--servercert sha256:…` line to copy into `oc_servercert`. That
refusal is the expected first step, not a failure.

<!-- [fr] -->
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

<!-- [en] -->
## The two “groups” of an AnyConnect gateway

One concentrator hosts several services, and two entirely different
mechanisms select one. Confusing them does not raise a syntax error: it
hands you **another service's login form**, so correct credentials are
refused and nothing points at the group.

| Profile field | openconnect | What it is |
|---------------|-------------|------------|
| `oc_usergroup` | `--usergroup=X` | the **URL path**: `--usergroup=X` and `https://host/X` are the same thing |
| `oc_authgroup` | `--authgroup=X` | a value to pick in a **dropdown** the server presents |

A site that hands you an `.xml` profile designates its service by the path;
a site that shows you a list to choose from in a screenshot designates its
own by the dropdown.

In a Cisco `AnyConnectProfile` file, `<UserGroup>` is the path and
`<HostName>` is only a display label — despite the tag name, it is not a
hostname; `<HostAddress>` is. `VPN › Import an AnyConnect profile (.xml)`
reads those three tags and writes presets into `private/vpn/presets/`, so
the field that actually decides which service you reach is never retyped.

<!-- [fr] -->
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

<!-- [en] -->
## SSO / SAML: what openconnect can and cannot do

When a gateway authenticates through an identity provider (Okta, Azure AD,
Duo), there is no password to send — a web page has to be completed. Cisco
signals this in **two** different ways, and only one of them works from a
plain CLI:

| Server announces | openconnect needs | Works with a distribution package |
|------------------|-------------------|-----------------------------------|
| `single-sign-on-external-browser` | `--external-browser=<cmd>` | **yes** — set `oc_external_browser` |
| `sso-v2` (embedded browser) | a built-in webview (libwebkit2gtk) | **no** — Debian, Ubuntu, Fedora and Arch all build without it |

The gateway decides which one, per tunnel group. When it asks for the
embedded browser and openconnect has no webview, it stops on:

<!-- [fr] -->
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

<!-- [common] -->
```
Please complete the authentication process in the AnyConnect Login window.
No SSO handler
Failed to complete authentication
```

<!-- [en] -->
`--external-browser` does **not** help there: openconnect only takes that
path when the server announced the external-browser method. Which one a
gateway wants can be read without sending any secret:

<!-- [fr] -->
`--external-browser` n'y change **rien** : openconnect ne prend ce chemin
que si le serveur a annoncé la méthode « navigateur externe ». Laquelle
une passerelle veut se lit sans envoyer aucun secret :

<!-- [common] -->
```bash
openconnect --protocol=anyconnect --usergroup=<GROUPE> \
    --authenticate --dump-http-traffic <passerelle> 2>&1 \
    | grep -E 'sso-v2|external-browser|No SSO handler'
```

<!-- [en] -->
### Installing the helper

`VPN › Install the client packages` offers it when the driver is
OpenConnect and no helper is found — and stays quiet otherwise. From the
command line:

<!-- [fr] -->
### Installer le greffon

`VPN › Installer les paquets client` le propose quand le pilote est
OpenConnect et qu'aucun greffon n'est trouvé — et se taît sinon. En ligne
de commande :

<!-- [common] -->
```bash
sudo bash script/install/install_vpn.sh openconnect --sso
```

<!-- [en] -->
Read what that step carries before accepting it. The helper's upstream has
been **unmaintained since 2023**, so the installer holds workarounds that
will not resolve on their own: its version pins are unsatisfiable on a
recent Python (pre-5 `lxml` does not build), Qt and `lxml` come from the
distribution rather than PyPI, and a call to `asyncio.get_event_loop()`
raises from Python 3.12 on — patched on every install, since any
reinstallation erases it. pip reports a pin conflict on `lxml` and
`keyring`; it is expected, those are the two pins deliberately relaxed.

Package names are **verified on Debian and Ubuntu only**; on the other
families they are best-effort, and a mistake there reads as "package not
found" without breaking anything else.

The venv belongs to the **user**, not root: the helper needs a display and
a keyring, which root does not have. The installer therefore refuses to run
without `sudo`, from which it reads who to install for.

<!-- [fr] -->
Lire ce que cette étape porte avant de l'accepter. L'amont du greffon n'est
**plus entretenu depuis 2023**, si bien que l'installateur porte des
contournements qui ne se résoudront pas d'eux-mêmes : ses épingles de
version sont intenables sur un Python récent (`lxml` d'avant la 5 ne
compile pas), Qt et `lxml` viennent de la distribution et non de PyPI, et
un appel à `asyncio.get_event_loop()` lève depuis Python 3.12 — corrigé à
chaque installation, puisque toute réinstallation l'effacerait. pip signale
un conflit d'épingles sur `lxml` et `keyring` : il est attendu, ce sont les
deux qu'on relâche sciemment.

Les noms de paquets ne sont **vérifiés que sur Debian et Ubuntu** ; sur les
autres familles ils sont donnés au mieux, et une erreur s'y lit « paquet
introuvable » sans rien casser d'autre.

Le venv appartient à l'**utilisateur**, pas à root : le greffon a besoin
d'un affichage et d'un trousseau, que root n'a pas. L'installateur refuse
donc de tourner sans `sudo`, dont il lit pour qui installer.

<!-- [en] -->
### Delegating the web form, keeping the tunnel

For a gateway that insists on the embedded browser, set `oc_sso_helper` to
an `openconnect-sso` executable. The driver then splits the work:

| Step | Who | Runs as | Carries |
|------|-----|---------|---------|
| SAML / MFA in a real browser | the helper, `--authenticate json` | **you** (needs your display and keyring) | returns `{host, cookie, fingerprint}` |
| bringing the tunnel up | this driver, `--cookie-on-stdin` | root, via `sudo` | the cookie, on standard input only |

That split is the whole point. The helper does *only* the SAML dance; the
**profile** stays the source of truth for the interface name, the added
routes, the state files and the diagnosis. A tunnel opened by the helper
itself would be called `tun0`, would leave nothing in `/run`, and `status`,
`diagnose` and `down` would not see it.

Two details make the cookie fail if you neglect them, and the driver handles
both: the **announced identity** must match on both steps (`oc_ac_version`
goes to the helper *and* to openconnect — a cookie issued to one client
version is refused to another), and the **fingerprint** the helper reports
wins over `oc_servercert`, because it is the one it authenticated against.
Many of these gateways present a chain the system store does not validate
(`signer not found`), and `--non-inter` would refuse it without a pin.

The cookie never touches a file: it lives in a variable, leaves by standard
input, and is masked from every display the moment it exists. On a machine
with no usable GPU — a virtual machine, typically — the embedded Chromium
falls back to Vulkan and the window dies mid-authentication; the driver
therefore forces software rendering unless those variables are already set.

Which path is taken is decided in one place, and reads in this order:

<!-- [fr] -->
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

<!-- [common] -->
| `oc_sso` | `oc_sso_helper` resolves | Path |
|---|---|---|
| yes | yes | helper authenticates, this driver mounts |
| yes | declared but not executable | **refused, and says so** — never a silent fallback |
| yes | no | `--external-browser`, openconnect alone |
| no | — | password from the vault |

<!-- [en] -->
A declared helper that cannot run is an error, not an invitation to take the
other path: falling back quietly would make the mount fail on `No SSO
handler`, three stages above the real cause — a wrong path.

`vpn.py status` and `diagnose` carry a `SSO helper` line: the resolved path,
`absent`, or `not applicable` when the profile authenticates by password.

<!-- [fr] -->
Un greffon déclaré qui ne peut pas s'exécuter est une erreur, pas une
invitation à prendre l'autre chemin : se replier sans bruit ferait échouer le
montage sur `No SSO handler`, trois étages au-dessus de la vraie cause — un
chemin fautif.

`vpn.py status` et `diagnose` portent une ligne `greffon SSO` : le chemin
résolu, `absent`, ou `sans objet` quand le profil authentifie par mot de
passe.

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
