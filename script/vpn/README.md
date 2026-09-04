
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

## An SSL VPN (AnyConnect), distribution by distribution

The `openconnect` driver speaks AnyConnect (Cisco), Pulse/Juniper,
GlobalProtect, Fortinet, F5 and Array. One command installs its client:

```bash
sudo bash script/install/install_vpn.sh openconnect
./.venv.erplibre/bin/python script/vpn/vpn.py check --driver openconnect
```

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

```
Please complete the authentication process in the AnyConnect Login window.
No SSO handler
Failed to complete authentication
```

`--external-browser` does **not** help there: openconnect only takes that
path when the server announced the external-browser method. Which one a
gateway wants can be read without sending any secret:

```bash
openconnect --protocol=anyconnect --usergroup=<GROUPE> \
    --authenticate --dump-http-traffic <passerelle> 2>&1 \
    | grep -E 'sso-v2|external-browser|No SSO handler'
```

### Installing the helper

`VPN › Install the client packages` offers it when the driver is
OpenConnect and no helper is found — and stays quiet otherwise. From the
command line:

```bash
sudo bash script/install/install_vpn.sh openconnect --sso
```

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

| `oc_sso` | `oc_sso_helper` resolves | Path |
|---|---|---|
| yes | yes | helper authenticates, this driver mounts |
| yes | declared but not executable | **refused, and says so** — never a silent fallback |
| yes | no | `--external-browser`, openconnect alone |
| no | — | password from the vault |

A declared helper that cannot run is an error, not an invitation to take the
other path: falling back quietly would make the mount fail on `No SSO
handler`, three stages above the real cause — a wrong path.

`vpn.py status` and `diagnose` carry a `SSO helper` line: the resolved path,
`absent`, or `not applicable` when the profile authenticates by password.

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
