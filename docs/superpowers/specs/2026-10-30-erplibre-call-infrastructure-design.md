# ERPLibre: call infrastructure through todo.py (coturn, public ntfy, ICE servers)

**Status:** draft for project 3 of the mobile chat
(`2026-10-25-erplibre-mobile-chat-design.md`; project 2,
`2026-10-28-erplibre-mobile-chat-notifications-design.md`, done in three lots).
**Builds on:** the ntfy tooling of `todo.py` (`script/install/install_ntfy.sh`,
`script/todo/ntfy_mobile.py` and its `LocalHost` / `SshHost`, « Préparer ntfy
pour ERPLibre mobile »), the nginx and certbot scripts, the qemu long tests,
the harness Odoo 18 of `long_test/mobile_sync_odoo.py`.

## Intent

Project 4 brings video calls between colleagues, peer to peer. Two phones or
browsers behind ordinary routers often cannot reach each other directly; a
TURN server relays them. Odoo 18 already knows how to hand TURN servers to
the browser (`mail.ice.server`), but nobody in an ERPLibre deployment has one,
and installing coturn right (ports, TLS, credentials, firewall) is the kind
of work people get wrong once and never touch again.

Project 2 also left one thing for here: the phone's notifications ride on the
user's own ntfy, installed so far only on a local development machine in
http. A production Odoo needs a public ntfy in https.

Project 3 makes both a menu in `todo.py`: pick a host, install coturn, ntfy or
both, then plug one or several Odoo servers into them. The same commands
serve a developer on a laptop and an administrator on a production host.

## Success

- From `todo.py`, an administrator installs coturn and ntfy on a fresh
  Debian, Ubuntu or Arch host reached over ssh, in production mode with
  Let's Encrypt, without editing a file by hand.
- « Add an Odoo server » makes that Odoo hand working TURN servers to the
  browser at the next call join, with temporary credentials when the
  `erplibre_turn` module is installed.
- « Check » says, in plain words, what works and what does not: TURN answers
  with the credentials Odoo hands out, the certificate is valid and renews,
  ntfy answers in https, the firewall lets the ports through.
- The same submenu installs a development setup on the local machine without
  nginx, in http or with a supplied certificate.
- Every step is proven by a long test on a throwaway VM, destroyed by
  `--detruire`.

## Failure, even if it technically works

- An open relay: a coturn anyone can use without going through Odoo, or one
  that relays into the host's private network.
- A credential that never expires, handed to every browser in clear, as the
  only option.
- An installer that reports success when the service did not start, or a
  certificate that renews for nginx but leaves coturn on the expired one.
- A firewall changed without asking, or ssh locked out by a rule.
- A second run that breaks the first install (the commands must be safe to
  run again).
- An Odoo whose own `mail.ice.server` rows, written by someone else, are
  erased.

## Decisions (the user's)

Recorded in `tasks/chat/p3-decisions.md`, 2026-10-30.

**Hosts and systems**

- The host is asked each time: any host reachable over ssh (a dedicated VPS,
  the Odoo server's own host) or the local machine. coturn and ntfy go
  together or apart, as chosen.
- Systems: Debian, Ubuntu (same path as Debian) and Arch.
- Install method: offered both ways, system packages with systemd, or
  containers. The container engine is Docker or Podman, whichever is
  installed. Development mode offers both methods too.

**Development and production**

- Production: ntfy behind nginx (the existing one, or one installed); coturn
  apart on 3478 and 5349 (TURN over TLS) plus its media port range; port 443
  stays nginx's.
- Development: works WITHOUT nginx, in one of two ways, as chosen: http with
  TURN without TLS (local network only, said in plain words), or https with
  a supplied certificate given straight to ntfy and coturn.
- Certificates: both must be supported — Let's Encrypt (the domain already
  points at the host; certbot through nginx, renewed by its timer, a deploy
  hook copies the certificate for coturn and reloads it) and a certificate
  supplied by hand (files given to `todo.py`).
- A production host with coturn but no ntfy (so no nginx of its own) gets
  its certificate one of three ways, as chosen: certbot standalone on port 80
  (a confirmed firewall rule for 80/tcp; through nginx instead when one
  already runs there), nginx installed anyway only to answer the ACME
  challenge, or a supplied certificate only. When coturn and ntfy share a
  host, one certificate covers both names.

**Existing installs**

- A ntfy or coturn already on the host that the tool did not install (the
  current `install_ntfy.sh` install with phones registered, a hand-made
  coturn) is adopted: `todo.py` shows the changes as a diff, keeps a backup,
  and records in the host state what was there before. ntfy users and tokens
  stay, so registered phones keep working. Uninstall removes only what the
  tool added.

**Firewall**

- If a firewall is active (ufw or nftables), `todo.py` shows the rules it
  would add and asks before opening. It reminds the user of the cloud
  provider's firewall, which it cannot see.

**Odoo servers**

- One coturn and one ntfy serve several Odoo servers: install once, then
  « add an Odoo server » as many times as needed.
- Odoo 18 only; Odoo 12 to 17 are refused with a message. `todo.py` detects
  `erplibre_turn` and, when it is on the addons path but not installed,
  offers to install it.
- Everyone who joins a call gets TURN credentials from `erplibre_turn`,
  guests and portal users included, as Odoo does without the module: anyone
  holding an invitation link gets a relay for the credential's lifetime.
  The private ranges denial below is what keeps that relay from reaching the
  host's network.
- « Add an Odoo server » reaches Odoo in one of two ways, as chosen: the web
  API with an admin account (asked, never kept), or ssh and `odoo-bin shell`
  on Odoo's host.
- TURN credentials, per Odoo server:
  - with the new module `erplibre_turn` installed: temporary credentials
    (coturn's shared secret mechanism). The module overrides
    `mail.ice.server._get_ice_servers`, keeps the secret in a system
    parameter, and builds the list itself, including a `turns:` entry. The
    lifetime is a system parameter, 24 h by default. It warns when the list
    passes 5 URLs;
  - without the module: a fixed coturn account written into
    `mail.ice.server`, 3 rows (STUN, TURN over UDP, TURN over TCP), and
    `todo.py` warns that TURN over TLS is not available (Odoo's type field
    offers only `stun:` and `turn:`);
  - `todo.py` detects the module.
- Existing `mail.ice.server` rows: `todo.py` shows them, replaces only the
  rows it wrote itself, and warns if the total passes 5 (Odoo sends at most
  5 rows to the browser, `search(limit=5)`, a Firefox cap).
- `erplibre_turn` is a separate small module, not part of
  `erplibre_mobile_chat`: browser calls must not depend on the mobile app's
  module.

**Menu**

- A submenu « Infrastructure d'appel » in `todo.py`: install on a host
  (coturn, ntfy or both); add an Odoo server; check; uninstall. It takes over
  the existing ntfy entries (install, « Préparer ntfy pour ERPLibre mobile »),
  which leave the Deploy menu.

**Tests**

- A throwaway qemu VM in `long_test` (Debian), installed over ssh, checked
  (TURN answers, ntfy in https with a supplied certificate, ICE servers
  written in a test Odoo), destroyed by `--detruire`. Real Let's Encrypt is
  not tested without a public domain.

## Controller's calls (the user may overrule)

- **« An Odoo server » is one URL and one database.** `mail.ice.server`, the
  system parameters and the module's install state are per database; the
  host state keys each plugged Odoo by `url|database`. The ntfy exempt host
  is per address, shared by the databases of one Odoo.
- **One secret per Odoo server, in coturn's own database.** With the module,
  each Odoo gets its own coturn shared secret; without it, its own fixed
  user. Both live in coturn's user database (`turnadmin`, SQLite), not in
  `turnserver.conf`: coturn reads them live, so adding, removing or rotating
  an Odoo never restarts coturn nor drops a running call on another Odoo.
  Removing an Odoo revokes only its secret or user. Running « add an Odoo
  server » again on the same Odoo rotates them.
- **Fixed account per Odoo server.** Without the module, each Odoo gets its
  own coturn user, so one leaked account is revoked alone.
- **Private ranges denied in production.** coturn 4.6 does not refuse to
  relay toward private addresses by default. Production denies the RFC 1918,
  loopback, link-local and CGNAT ranges (`denied-peer-ip`), so a stranger
  holding a credential cannot reach the host's network. Development on a
  local network keeps them allowed, said in plain words.
- **Credential lifetime facts.** The browser reads the ICE list once when it
  joins a call (`/mail/rtc/channel/join_call`) and reuses it for every peer
  that joins later; coturn checks the credential when an allocation is made,
  not during an open session. An expired credential therefore never cuts a
  running relay; it only refuses a new allocation for a peer that joins a
  call more than one lifetime after the user joined. 24 h covers any real
  call. (The question asked earlier assumed a cut at expiry; that assumption
  was wrong, the default stays as chosen.)
- **Nothing configured, nothing returned.** With the module installed but no
  secret set, `_get_ice_servers` returns what Odoo returns without the module
  (Odoo's own test expects `iceServers` false with no row); with the module
  and a secret, the module's list replaces the rows the module itself wrote,
  and other rows written by hand are appended after it, within the cap.
- **The ntfy part of « add an Odoo server ».** Odoo has no ntfy setting (the
  phone registers its endpoint). On the ntfy side it adds Odoo's outgoing
  address to `visitor-request-limit-exempt-hosts`, so a busy Odoo is not rate
  limited. Behind nginx, ntfy runs with `behind-proxy: true`; without it every
  client looks like 127.0.0.1 and exempting 127.0.0.1 would exempt everyone.
- **Remote execution reuses `ntfy_mobile.LocalHost` / `SshHost`**
  (`ssh -t`, `sudo sh -c`, an interactive sudo password works; files written
  with a backup and a diff). Secrets go in the script body or the
  environment, never in argv, and are redacted from logs.
- **State on the host, not on the laptop.** What `todo.py` installed (method,
  mode, domain, ports, the Odoo servers plugged in, which `mail.ice.server`
  rows it wrote) is kept in one root-only file on the host
  (`/etc/erplibre-call/state.json`), read by check, add, uninstall and by a
  second install. No secret is kept on the machine running `todo.py`.
- **Idempotent.** Every command reads the host state first and changes only
  what differs; a second install with the same answers changes nothing and
  says so.
- **Check is read-only** and runs a real TURN allocation from the machine
  running `todo.py` (a small standard-library TURN client: the laptop has no
  `turnutils_uclient`), plus the certificate's expiry and issuer, ntfy's
  `/v1/health` over https, and the firewall rules. By default it computes
  each plugged Odoo's credentials from coturn's database on the host (as
  root, non-interactive), which proves coturn; « check through Odoo », asked
  per run, logs into one plugged Odoo and allocates with the list Odoo
  really hands out, which proves Odoo's side too. Fixed account passwords
  are therefore kept readable by root on the host (coturn's database), never
  on the laptop.
- **Uninstall** stops and removes the services, the configuration, the
  firewall rules it added, the nginx site it added and the certbot deploy
  hook; it keeps the certificates and ntfy's user database unless the user
  answers « yes » to removing them; it removes from each plugged Odoo only
  the rows it wrote and the module's secret parameter.
- **Media port range.** coturn's default 49152–65535 in production; a
  smaller range (asked, default 49152–49252) in development and in
  containers, where a large published range is slow to set up.
- **The existing ntfy defects found during the recon are fixed in lot 1**,
  since lot 1 takes those entries over: the install reports success even when
  it failed; the systemd unit of the binary install leaves `/var/lib/ntfy`
  read-only; the admin user created as root can leave `user.db` owned by
  root.

## Constraints found in Odoo 18, coturn, ntfy and the repository

- `mail.ice.server` (`mail/models/mail_ice_server.py`): `server_type` is
  `stun` or `turn`, `uri` has no scheme, `username` and `credential` in clear;
  `_get_local_ice_servers` returns at most 5 rows; Twilio, when enabled, comes
  first in `_get_ice_servers`. The only caller is `_rtc_join_call`, through
  `/mail/rtc/channel/join_call` (`auth=public`, guests included). The ICE list
  also goes into the SFU token. The browser's `hasTurn` only recognises
  `turn:` (to check whether `turns:` counts).
- coturn temporary credentials: `use-auth-secret` with `static-auth-secret`
  and a `realm`; username `expiry_timestamp:userid`; password base64 of
  HMAC-SHA1(secret, username).
- Debian's coturn runs as user `turnserver`, cannot read `/home` nor certbot's
  `live/` directory (root only); `/etc/turnserver.conf` must be
  root:turnserver 0640. TLS certificates reload on SIGUSR2. `external-ip` is
  needed behind NAT (most cloud hosts).
- `install_ntfy.sh` today: local only, systemd only, TLS on 443 itself (clashes
  with nginx), no `behind-proxy`, no firewall, no container, no uninstall.
- `container_runtime.py` detects Docker or Podman only locally: the remote
  probe is a new shell script sent through `host.run`.
- `deploy_nginx_and_certbot.py` uses `os.system` without checking results,
  has no `nginx -t` and no deploy hook, and assumes Debian (Arch has no
  `sites-enabled`). The Odoo 18 SSL nginx template is a usable model for the
  ntfy site.
- No firewall detection exists anywhere in the repository.
- Moving the ntfy entries out of Deploy breaks tests that pin its numbering
  (`test_todo_ntfy_mobile.py`, `test_proxmox_deploy.py`) and messages that
  name the old path (`ntfy_mobile_menu.py`, two `.base.md` docs): they move
  with the entries.
- Long tests: a VM test must be added to `descente.py` `SCRIPTS` and
  `longtest_menu.py` `SCRIPTS_DESCENTE`, or a `--detruire` launched during a
  run destroys its VM. Debian VMs need `--version 13` and `drapeaux_cache()`.
  Arch exists (`deploy_qemu --distro arch`) and needs the full pacman upgrade
  first. A harness Odoo database must not be named `mobile_sync_*` (that
  test's `--detruire` drops them). `local_cert.issue()` produces a local CA
  and a certificate with an IP SAN for the supplied-certificate checks.
- `odoo-bin shell` scripts must end with `env.cr.commit()`. An admin with
  two-factor authentication needs an API key for the web API method.

## Lots

1. **Host installer, packages and systemd.** The submenu and the move of the
   ntfy entries; host choice (local or ssh) and system detection (Debian,
   Ubuntu, Arch); coturn and ntfy by system packages with systemd;
   development mode in http or with a supplied certificate; firewall
   detection and confirmed opening; host state file; adoption of a ntfy or
   coturn already there (diff, backup, phones keep working); check (TURN allocation,
   ntfy health, certificate, firewall); uninstall; the three ntfy defects.
   Long test: a Debian 13 VM, both services in development mode with a
   supplied certificate, check green, uninstall leaves nothing; plus an Arch
   VM for the package path.
2. **Production.** nginx (existing or installed, Debian and Arch layouts) with
   the ntfy site and `behind-proxy`; Let's Encrypt through certbot with the
   deploy hook for coturn; the coturn-only host's three ways (certbot
   standalone on 80, nginx for ACME only, supplied only); supplied
   certificate in production; TURN over TLS
   on 5349; private ranges denied; `external-ip`. Long test: production mode
   with a supplied certificate standing in for Let's Encrypt (the deploy hook
   is run by hand to prove the coturn copy and reload).
3. **Odoo servers.** Module `erplibre_turn` 18.0.1.0.0 (temporary
   credentials, `turns:` entry, lifetime parameter, warning past 5 URLs, its
   own tests); « add an Odoo server » by web API or by `odoo-bin shell`, Odoo
   18 only, with module detection and the offer to install it, per-Odoo secret or fixed account, the 3-row fallback,
   rows kept apart from hand-written ones; the ntfy exempt host. Long test: a
   harness Odoo 18 with and without the module, a real TURN allocation with
   the credentials Odoo hands out, second Odoo on the same coturn, removal of
   one Odoo leaves the other working.
4. **Containers.** Docker or Podman, detected on the host; coturn with host
   networking, ntfy with its data volume; both modes; same check and
   uninstall. Long test: the Debian VM with Docker, then with Podman.

## Left to the builder

- Whether coturn 4.6 (Debian 13, Ubuntu LTS, Arch, the official image)
  accepts several shared secrets in its database, and whether one coturn can
  serve temporary credentials and fixed accounts at the same time. If it
  cannot mix, `todo.py` refuses to plug a module-less Odoo into a coturn
  already serving module Odoos (and the reverse) and says why; the builder
  reports the finding before lot 3. Proven first in lot 1's VM, since the
  storage choice rests on it.
- The exact firewall rules (ufw commands, an nftables table of its own),
  provided ssh's port is always kept open first.
- The ntfy container image and coturn image to use (official ones), and how
  their configuration files are mounted.
- The TURN client used by check (a minimal STUN/TURN Allocate over UDP and
  TCP, standard library only).
- The nginx site for ntfy (websocket upgrade, long timeouts for streaming).
- How the module marks the rows it owns (a technical field, or the URI
  pattern), as long as hand-written rows are never touched.
- Wording of every screen, French first, through `todo_i18n.py`.

## Non-goals

- Video calls themselves (project 4), and an SFU.
- iOS and APNs.
- Twilio (Odoo's own setting stays as is).
- High availability, several coturn hosts behind one name, monitoring.
- A public ntfy shared between organisations.
