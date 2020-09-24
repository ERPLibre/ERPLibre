# Poetry
## Add automatically dependencies
Add your dependencies in files [requirements.txt](../requirements.txt) and run script
```bash
./script/poetry_update.py
```
This will search all requirements.txt files and update pyproject.toml, to run poetry update.

## Add manually dependencies
The automatic script will erase this dependency, but you can add it for your locally test.
```bash
poetry add PYTHON_MODULE
```
