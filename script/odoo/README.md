
# Odoo instance tools

| File | What it does |
|------|--------------|
| `update_module.py` | updates installed modules of an instance run by systemd: stop, back up, update, restart, check |
| `warmup_http.py` | wakes the registry up as soon as the server listens; launched by `run.sh` |
| `migration/` | migration tools, see [migration/README.md](migration/README.md) |

## update_module.py

```bash
./script/odoo/update_module.py --module my_module_a --dry-run
sudo ./script/odoo/update_module.py --module 'my_module_*' --db demo_db
```

It is also reachable from `make todo`: `Execute > Production`, which runs
the simulation first and asks before the real run.

What it does, in order:

1. **Detection, nothing stopped.** The unit is `--service`, else the
   `erplibre…`/`odoo…` unit whose `WorkingDirectory` is this checkout, else
   the only active one. Its account, directory, command line and
   environment come from `systemctl show`. The Odoo configuration, the
   database (`--db`, else `-d` of the unit, else `db_name`), the HTTP port
   and the modules (patterns expanded over `addons_path`, only folders with
   a `__manifest__.py`) are deduced from them. Anything missing refuses
   with code 2.
2. **Root and lock.** Root is required (except `--dry-run`); one lock per
   database, code 75 when another update holds it.
3. **Stop.** The state before is read from `ActiveState`; without an
   answer from systemctl nothing is stopped (code 2). After `systemctl
   stop`, the unit must be `inactive` or `failed` (not `deactivating`).
   If the port still answers, or an Odoo process runs on the same database
   outside the unit, the update is refused unless `--force`.
4. **Backup** (unless `--no-backup`), after the stop so that it is
   consistent: `odoo_bin.sh db --backup` into `image_db/`, as the unit's
   account. Requires `odoo_bin.sh` in the unit's directory, an `image_db/`
   folder the unit's account can write to, and `list_db` not set to
   `False`. The zip is written as `<name>.partial.zip`, read back, then
   renamed: a file with the final name is always a complete backup.
5. **Update**: the unit's command line followed by `-c CONFIG -d DB -u
   MODULES --stop-after-init --no-http --workers=0 --max-cron-threads=0`,
   as the unit's account — the repeated `-c` keeps the update on the file
   the detection and the backup read (`--odoo-conf` included). It fails on a non-zero code, on `--timeout`, or on an
   `ERROR`/`CRITICAL` line in its output or in what was appended to the
   configured `logfile`. `--ignore-error REGEX` excludes known lines.
6. **Restart**, if the unit was running: wait for `active` and the port
   (`--start-wait`), one HTTP request, then the unit's journal and the
   `logfile` are read since the start.

The unit is never modified: the tool only reads it and runs `systemctl
stop` / `start`. Whatever happens after the stop — failure, exception,
Ctrl-C, SIGTERM — a unit that was running is restarted. Nothing is
restored: the tool does not replace the code; the backup is there for a
restore decided by a person.

| Code | Meaning |
|------|---------|
| 0 | success (or simulation) |
| 1 | update failed, service restarted |
| 2 | refused before anything was stopped |
| 75 | another update of this database is running |
| 130 | interrupted, service restarted |

The update log goes to `--log-dir` (default `/var/log/erplibre`, falling
back to the temporary directory).
