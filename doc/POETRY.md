# Poetry

## Add dependencies automatically

Add your dependencies in file [requirements.txt](../requirements.txt) and run script

```bash
./script/poetry_update.py
```

This will search all `requirements.txt` files and update `pyproject.toml` and it will update poetry

Priority dependencies in ./requirements.txt, after it's ./odoo/requirements.txt, after it's highest version values.

TODO add option to only add missing dependencies and ignore update.

## Add dependencies manually

The automatic script will erase this dependency, but you can add it for your local test.

```bash
poetry add PYTHON_MODULE
```

## Error `relative path can't be expressed as a file URI`

If you got this error `relative path can't be expressed as a file URI` when executing poetry, delete directory
artifacts: `rm -rf artifacts/` and rerun the update.
