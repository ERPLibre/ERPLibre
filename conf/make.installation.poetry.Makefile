###########
# INSTALL #
###########

.PHONY: install_venv_with_minimal_pip
install_venv_with_minimal_pip:
	# This install .venv.odoo.version with poetry without complete pip installation
	# This is interested to create new pip installation
	WITH_POETRY_INSTALLATION=0 ./script/install/install_locally.sh

##########
# poetry #
##########
.PHONY: poetry_update
poetry_update:
	./script/poetry/poetry_update.py

.PHONY: poetry_update_force
poetry_update_force:
	# Use this to recreate pip dependency from new installation, this will ignore freeze versions
	./script/poetry/poetry_update.py -f

