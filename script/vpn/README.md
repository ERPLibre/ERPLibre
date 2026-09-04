
# VPN — five open tunnels, secrets in a KeePassXC vault

`vpn.py` brings up, tears down and diagnoses a VPN tunnel. One driver per
technology, five of them, all free software.

The split is the whole design: what is *not* secret (host, user, routes, MTU)
lives in readable JSON configuration; the pre-shared keys and the passwords
live in a KeePassXC `.kdbx` vault. A profile can therefore be shown, compared
and shared without handing over the means to bring the tunnel up.

## Which one to pick

| Driver | Pick it when | Secrets in the vault |
|--------|--------------|----------------------|
| `l2tp_ipsec` | the far side imposes it: a router, a firewall, Windows RRAS | PSK + PPP password |
| `wireguard` | you control both ends — fastest, simplest | private key (+ optional PSK) |
| `openvpn` | the site handed you a `.ovpn` file | password, if the file needs one |
| `openconnect` | Cisco AnyConnect, Pulse, GlobalProtect, Fortinet appliances | password |
| `sshuttle` | all you have is SSH access — nothing to install on the far side | none: SSH keys do the work |

## Commands

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

Everything is also reachable from the CLI: **TODO › Execute › Deployment ›
VPN**, and from **TODO › Execute › Network › VPN** — a tunnel gets looked for
in both places. The menu is where profiles are created and secrets are typed
in; `vpn.py` is what the menu runs. Connecting from the menu shows the plan
first and asks before running it.

Run it as **yourself, not under sudo**: the vault lives in your home and its
master password is yours to type. Each privileged step calls `sudo` on its
own, and `--dry-run` shows every one of them without running any.

## Where things live

| Path | Content |
|------|---------|
| `private/todo/todo_override_private.json` | your profiles — gitignored, 0600 |
| `script/todo/todo.json` | the `vpn` section, empty: profiles shared by a team can go here |
| your `.kdbx` vault | one entry per profile, `ERPLibre VPN / <profile>` |
| `/dev/shm/erplibre-vpn/<profile>/` | 0700 root — **the secrets**, in tmpfs, erased on `down` |
| `/run/erplibre-vpn/<profile>.*` | non-secret state (chosen interface, pid, log), readable without sudo |
| `/etc/ipsec.conf`, `/etc/ipsec.secrets` | L2TP only: a marked block, removed on `down` |

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

## Adding a driver

`drivers/base.py` states the contract *and* carries everything true of all
technologies: directory layout, state kept between processes, routes,
systemd-resolved, the standard status checks. A new driver declares what is
its own — packages, secrets, profile fields, the form the menu unrolls, the
sequence up and down — and executes nothing: it asks a `Runner`, which either
runs or merely shows. Registering it is one line in `drivers/__init__.py`, and
`test_vpn_drivers.py` picks it up from the registry: the no-secret-on-a-command
-line rule applies to it whether or not anyone thought about it.
