# Poetry
## Add automatically dependencies
Add your dependencies in file [requirements.txt](../requirements.txt) and run script
```bash
./script/poetry_update.py
```
This will search all `requirements.txt` files and update `pyproject.toml` and it will update poetry

TODO add option to only add missing dependencies and ignore update.

## Add manually dependencies
The automatic script will erase this dependency, but you can add it for your local test.
```bash
poetry add PYTHON_MODULE
```
