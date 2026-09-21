
# Deploying over SSH: the named target

`TODO › Deploy › SSH (remote host)` acts on a machine described once and
found again afterwards. Before that, each of its eleven verbs asked five
questions — address, account, port, key, path — and remembered none.

## What a target holds


| field | |
|---|---|
| `name` | `[a-z0-9][a-z0-9_-]{0,30}` |
| `target` | `user@host`, or a `~/.ssh/config` alias |
| `jump` | bastion, empty for a direct connection |
| `port` | empty: ssh decides, so an alias keeps its own |
| `identity` | private key, empty: `~/.ssh/config` decides |
| `path` | where ERPLibre lives, default `~/erplibre_deploy_2` |
| `domain` | non-empty ≡ served over HTTPS behind nginx |
| `admin_email` | for the certificate |
| `verdict` `version` `sudo` `last_probe` | what the probe found |

## Two stores, and why

The **inventory** — which machines exist — is site data. It lives under
`deploy_targets` in the three configuration files that `ConfigFile` merges,
and is written only to `private/todo/todo_override_private.json`: the only
one of the three that is gitignored, written atomically in `0600`.

The **selection** — which machine is being addressed right now — is a screen
preference and lives with the other preferences. Keeping the two apart is
deliberate: resetting preferences must not delete an inventory.

Only the *name* is remembered, and the record is re-read on every read.
Copying the record would age it at the first edit, and the screen would
name a machine that has changed address.

A target from the shared file can be corrected: the private entry replaces
it under the same name, and deleting the correction brings the shared one
back.

## No `prod` flag

The word covers two distinct questions, and the target answers both without
naming either:

- *is this service exposed?* — answered by `domain`. Non-empty means served
  behind nginx with a certificate.
- *what posture does the machine have?* — answered by `path`: a checkout
  under `/opt` and one under a home directory are not the same install.

One field, one truth. A boolean read in several places would drift from
whichever of the two questions it was not answering.

## Checking a target

`SSH - Check connection` reads the version file at the target's own path. It
reports per layer, because "ssh gets through, the product is missing" and
"nothing answers" are fixed from opposite sides. Elevation is *observed*,
not required: two verbs out of eleven need it, and refusing the machine for
them would close the other nine. What it finds is written onto the record,
with its date.
