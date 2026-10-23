
# Improve Odoo: ERPLibre's Odoo fork

Each `odooX.0/odoo` checkout is the branch `ERPLibre/X.0` of the repository
ERPLibre/odoo. This page lists what that branch adds to Odoo, version by
version, and where each addition lives: in the Odoo core, or in a module.

## Upstream: OCA/OCB

The fork follows OCA/OCB, the community branch of Odoo, not Odoo itself. The
manifest says so with three attributes on the `odooX.0/odoo` project:

```xml
<project
    name="odoo.git"
    path="odoo18.0/odoo"
    remote="ERPLibre_origin_odoo"
    fork-upstream-remote="OCA"
    fork-upstream-name="OCB.git"
    fork-upstream="18.0"
    revision="ERPLibre/18.0"
/>
```

What the fork carries on top of OCB, once the `OCA` remote is fetched:

```bash
git -C odoo18.0/odoo log --oneline OCA/18.0..ERPLibre/18.0
git -C odoo18.0/odoo diff --stat OCA/18.0 ERPLibre/18.0
```

Bringing OCB's new commits into the fork is an **upgrade**, described in
[GIT_REPO.md, "Update or upgrade"](./GIT_REPO.md#update-or-upgrade).

## Policy

The core diverges from OCB only where a module cannot do the job. Every other
change lives in a module. The command line commands live in the module
`erplibre_odoo_cli_base`, in the repository `ERPLibre_erplibre_addons`
(`odooX.0/addons/ERPLibre_erplibre_addons`). The module is never installed
(`installable: False`): it only carries a `cli/` package, which `odoo-bin`
imports before it runs a command.

A smaller core diff means fewer conflicts at each OCB upgrade, and a core that
any OCB user recognises.

## Matrix

`core`: the patch is a commit of the fork. `module`: the feature comes from
`erplibre_odoo_cli_base`, the fork does not carry it. `OCB`: OCB already
behaves this way, no patch is needed. `-`: absent.

| Patch | 12 | 13 | 14 | 15 | 16 | 17 | 18 |
|---|---|---|---|---|---|---|---|
| P1 uninstall from the command line | core | core | core | core | module | module | module |
| P2 `db` command | core | core | core | core | module | module | module |
| P3 `i18n` command | core | core | core | core | module | module | module |
| P4 install and apply a theme | core | core | core | core | module | module | module |
| P5 Message-ID `erplibre` | - | - | - | - | core | core | core |
| P6 push notification error hidden | - | - | - | - | - | - | core |
| P7 `partner_autocomplete` not auto-installed | - | core | - | - | core | core | OCB |
| P8 `web_unsplash` not auto-installed | core | core | core | core | - | - | - |
| P9 login without trailing spaces | core | core | core | core | - | - | - |
| P10 fixes of one version | core | - | core | core | - | - | - |

From 16 to 18, P1 to P4 come from `erplibre_odoo_cli_base`: the 16 and 17
forks are OCB plus P5 and P7, the 18 fork is OCB plus P5 and P6. In 12 to 15,
P1 to P4 stay in the core.

## The patches

### P1 Uninstall from the command line

When a module breaks the web client, the interface that would uninstall it no
longer loads. The command line uninstalls the listed modules and every
installed module that depends on them.

- 12 to 15: server option `--uninstall a,b`, in `odoo/modules/loading.py`
  and `odoo/tools/config.py`. In 14 and 15, a follow-up hides an empty
  option value.
- 16 to 18: `odoo_bin.sh module uninstall -d DB a,b`, from the module. Only
  modules in the `installed` state are uninstalled, as before.

### P2 The `db` command

OCB's `db` command loads, dumps, duplicates, renames and drops a database. The
ERPLibre command also restores an image of `./image_db/`, creates an
initialised database (language, admin login and password, country), lists the
databases and prints the Odoo version. The master password comes from the
`MASTER_PWD` environment variable: an argument is readable by every user of
the machine in `/proc`.

- 12 to 15: `odoo/cli/db.py` replaced by a command with flags (`--restore`,
  `--restore_image`, `--clone`, `--create`, `--backup`, `--drop`, `--list`,
  `--list_incompatible_db`, `--version`).
- 16 to 18: `odoo/cli/db.py` is OCB's. The module's `db` inherits it and adds
  `create`, `list`, `list-incompatible`, `version`, `--image` on `load` and
  `dump`, and a `drop` that checks the master password. On 16 and 17, whose
  OCB `load` has no `--move`, the module adds it.

### P3 The `i18n` command

Writes the `.pot` and the `.po` of an installed module into a directory, for
translators, without the interface.

- 12 to 15: `odoo/cli/i18n.py`.
- 16 to 18: the module's `i18n`, same options.

### P4 Install and apply a theme

Installing a theme module with `-i` does not apply it to the website: the
website's "Choose theme" button does that (copy the theme's views onto the
website, set it as the website's theme).

- 12 to 15: server option `--install-theme theme_x`, in
  `odoo/modules/loading.py` and `odoo/tools/config.py`. 12 fixes the
  option's empty default; 14 and 15 hide an empty value.
- 16 to 18: `odoo_bin.sh theme apply -d DB theme_x`, from the module. A theme
  the database does not list yet is found after refreshing the module list.
  The module installs the theme when needed, then calls the button's own
  method; on 16, whose button builds the website editor URL from the HTTP
  request, it runs the button's steps without that last one.

### P5 Message-ID `erplibre`

`odoo/tools/mail.py` builds the Message-ID of the e-mails Odoo sends. The
patch writes `erplibre` where Odoo writes `openerp`. It stays in the core: the
function is a module-level helper that the mail code calls directly.

- 16, 17, 18: one line of `odoo/tools/mail.py`.

### P6 Push notification error hidden

When the browser refuses push notifications, the mail web client shows a
sticky red notification at every load. The patch keeps the console warning
and drops the notification. It stays in the core: the call sits in the middle
of a patched method of the web client.

- 18: `addons/mail/static/src/webclient/web/webclient.js`.

### P7 `partner_autocomplete` not auto-installed

`partner_autocomplete` sends partner data to an Odoo IAP service. The patch
sets `auto_install: False`.

- 13: `iap` and `partner_autocomplete`; 16 and 17: `partner_autocomplete`.
- 18: OCB already sets `auto_install: False` for both; no patch.

### P8 `web_unsplash` not auto-installed

`web_unsplash` calls the Unsplash service from the image dialogs. The patch
sets `auto_install: False` in `addons/web_unsplash/__manifest__.py`.

- 12 to 15.

### P9 Login without trailing spaces

A mobile keyboard's autocompletion adds a space after the login. Login and
password reset strip it (`addons/web/controllers/main.py`,
`addons/auth_signup/models/res_users.py`).

- 12 to 15.

### P10 Fixes of one version

| Version | Commit | Change |
|---|---|---|
| 12 | e8e18c1b | `exec_pg_command` works with PostgreSQL 17 client tools (`odoo/tools/misc.py`) |
| 12 | 441ecac1 | `website_event` geolocation checks the event before using it |
| 12 | 43562f2c | `website`: header option for the navbar height |
| 12 | cd16be9b | `abstract_field.js` checks that a field is focusable |
| 12 | 7d5cfeef | `requirements.txt` aligned with OCA |
| 12 | c051702e | sale report: no salesperson line when it is empty |
| 12 | 64a5dd16 | sale portal: product error shown instead of an endless loading |
| 14 | 4d166425 | web: an image that cannot be shown is hidden |
| 14 | b9f96122, 136c1b1a | `packaging` instead of the deprecated `distutils` versions |
| 14, 15 | 0bbc0c2f, e9f9d7af | mail: `fr_CA` translation of the sent e-mails |
| 14, 15 | afc23de6, 3549b881 | mail: CC and TO fields for `mail_thread_cc` |
| 14, 15 | eb61b7a4, dab04fe5 | mail: suggested recipient name formatted |

## The command line module

`./odoo_bin.sh` is the entry point. Old flag syntax and new syntax:

| Old (12-15 fork) | New |
|---|---|
| `db --create --database DB [--demo] [--user_lang L] [--user_login U] [--user_password P] [--user_phone N] [--user_country_code C]` | `db create [-f] [--demo] [--lang L] [--login U] [--password P] [--phone N] [--country C] DB` |
| `db --list` | `db list` |
| `db --list_incompatible_db` | `db list-incompatible` |
| `db --version` | `db version` |
| `db --drop --database DB` | `db drop [--if-exists] DB` |
| `db --restore --database DB --restore_image IMG` | `db load [-f] [-n] [--move] [DB] --image IMG` |
| `db --restore --database DB --restore_db_file FILE` | `db load [-f] [-n] [--move] [DB] FILE` |
| `db --backup --database DB --restore_image IMG` | `db dump DB --image IMG` |
| `db --backup --database DB --restore_db_file FILE` | `db dump DB FILE` |
| `db --clone --from_database SRC --database DST` | `db duplicate [-f] [-n] SRC DST` |
| - | `db rename [-f] SRC DST` |
| `i18n -d DB --module M --addons_path OUT` | `i18n -d DB --module M --addons_path OUT` |
| `./run.sh --no-http --stop-after-init -d DB --uninstall a,b` | `module uninstall [-c FILE] -d DB a,b` |
| `./run.sh --no-http --stop-after-init -d DB --install-theme T` | `theme apply [-c FILE] -d DB T` |

- `MASTER_PWD`: `db drop` checks the master password first, read from this
  environment variable (`admin` when unset), then looks at the database.
  `-f` on `db create`, `db load`, `db duplicate` and `db rename` checks it
  too before it deletes an existing database; OCB's `-f` does not.
- `--if-exists`: without it, dropping an absent database is an error.
- `--image NAME`: `./image_db/NAME.zip`; a value containing `/` is a path
  (`.zip` appended when missing). `db load --image NAME` without a database
  name creates the database `NAME`.
- `db list`, `db list-incompatible` and `db version` print only their data on
  stdout, no log line.
- Global options come before the subcommand, as with OCB: `db -c FILE list`.
- Discovery: `odoo-bin` finds the module's commands through the addons path
  known when it starts, the configuration file of `ODOO_RC`. `./odoo_bin.sh`
  exports `ODOO_RC` (the repository's `config.conf`). A bare `odoo-bin` needs
  `ODOO_RC`, or `--addons-path=...` written before the command name.

## Older versions

12 to 15 keep the old commands in the core. `./odoo_bin.sh` decides from the
core of the active version (`.odoo-version`): when
`odooX.0/odoo/odoo/cli/db.py` lacks `_check_target`, the method of OCB's `db`
command, the core carries the old commands, and `./odoo_bin.sh` hands `db`,
`module` and `theme` to `script/database/odoo_db_legacy.py`, which turns the
new syntax into the old flags and server options. That is 12 to 15 always,
and a 16 or 17 fork still on its old commits. `i18n` passes unchanged. The
translation has known limits:

- `db load` on 12 to 15 always restores as a moved database (the UUID is
  kept); `--move` changes nothing there. On an old 16 or 17 fork, `-n` and
  `--move` become `--neutralize` and `--move_database`.
- No `--neutralize` (`-n`) on 12 to 15; no `db rename`, no `db dump` to
  stdout, no `db load` from a URL: the translator stops with exit code 2.
- `db create -f`, `db load -f` and `db duplicate -f` drop through the old
  `--drop`, which checks the master password (`MASTER_PWD`).
- Global options other than `-c` (`--db_host`...) are refused before the `db`
  subcommand.

The fork and the module go together. Next to an old core, the module
registers no command (its `cli/__init__.py` makes the same test), so the
translation works whether the module is there or not. On a core with OCB's
`db` but without the module, `db`, `module` and `theme` do not exist:
`./odoo_bin.sh` stops with exit code 2 and names the missing module.
