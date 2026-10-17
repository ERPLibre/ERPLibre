
# Execute ERPLibre

## Start database

```bash
sudo systemctl start postgresql.service
```

## Run ERPLibre

### Method 1

Simply

```bash
./run.sh
```

Without any argument, ERPLibre picks the database for you: with a single
one it starts on it, with several it shows a numbered menu. It only asks
when a real terminal is there — a service started by systemd behaves
exactly as before.

Two options steer that, and neither reaches Odoo:

| option | effect |
|---|---|
| `--auto-erplibre` | pick the database even when other arguments are given |
| `--no-cli-erplibre` | never show the menu; a lone database is still taken |

Naming a database yourself — `-d`, `--database` — turns the whole thing
off, and so does a `db_name` set in the configuration file.

With arguments

```bash
./run.sh -h
```

### Method 2

Execute your own python script:

```bash
./run.sh --log-level debug
```

### Update all

Great idea to run it when updating Odoo, it updates each module database.

```bash
./run.sh -d [DATABASE] -u all --log-level debug
```

### Update module

```bash
./run.sh -d [DATABASE] -u [module] --log-level debug
```

### Test

First execution, install you requirements, choose a new database.

```bash
./run.sh -d [DATABASE] -i [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

Execute your test on a specific module.

```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test
```

Execute your test on a specific module with tags.

```bash
./run.sh -d [DATABASE] -u [module to test] --test-enable --no-http --stop-after-init --log-level=test --test-tags [module_name][tags]
```

### Browser tests (tours, hoot)

Odoo tours, hoot tests and every `HttpCase` that drives a browser need two
things, and miss either one silently: each such test raises `SkipTest`, the
run ends green, and only a warning in the log — `Chrome executable not found`
or `websocket-client module is not installed` — tells that nothing ran.

- **A Chrome or Chromium in the `PATH`.** On Linux, Odoo looks for
  `google-chrome`, `chromium`, `chromium-browser` then `google-chrome-stable`;
  on macOS, `Google Chrome.app` then `Chromium.app` under `/Applications`.
  `make install_browser_test` installs one for the detected distribution:
  `chromium` from the system packages on Debian, Linux Mint, Fedora, the RHEL
  family (through EPEL), openSUSE and Arch, Google Chrome on macOS, and the
  Google Chrome `.deb` on Ubuntu, whose `chromium-browser` is a snap: the snap
  has its own `/tmp`, where Odoo never finds the debugging port of the
  browser. A snap Chromium already in the `PATH` therefore does not count as
  installed. On NixOS, declare `chromium` in `environment.systemPackages` or
  run the tests in `nix-shell -p chromium`. The target is not part of
  `make install_os`, a full browser being useless on a production server.
  `--dry-run` shows the commands without running them.
- **The `websocket-client` Python package in the Odoo venv.** It is declared
  in the Odoo 18 dependencies; an existing venv receives it with
  `poetry install --no-root`, run in that venv. When the lock file is older
  than the pyproject, Poetry refuses that command (`pyproject.toml changed
  significantly since poetry.lock was last generated`): run `poetry lock`
  first, in the same venv, with network access.

The script reports both. Then run the tests as above, with a tag that selects
them, for instance `--test-tags=/web:WebSuite` for the hoot suite of `web`.

```bash
make install_browser_test
./script/install/install_browser_test.sh --dry-run
```