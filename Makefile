SHELL := /bin/bash
#############
#  General  #
#############
# ALL
.PHONY: all
all: doc

###############
#  Detect OS  #
###############
# https://stackoverflow.com/questions/714100/os-detecting-makefile
DETECTED_OS := $(shell uname -s)
############################
#  Detect browser command  #
############################
#BROWSER := ls
ifeq ($(DETECTED_OS),Darwin)
	BROWSER := open
else
	ifeq ($(DETECTED_OS),Linux)
		BROWSER := xdg-open
	else
		ifeq ($(OS),Windows_NT)
			BROWSER := start
		else
			BROWSER := ls
		endif
	endif
endif

############
#  docker  #
############
# build docker
.PHONY: docker_build
docker_build:
	./script/docker_build.sh

# build docker release
.PHONY: docker_build_release
docker_build_release:
	./script/docker_build.sh --release

# docker clean all
.PHONY: docker_clean_all
docker_clean_all:
	docker system prune -a --volumes

##############
#  Git repo  #
##############
# clear all repo DANGER
.PHONY: repo_clear_all
repo_clear_all:
	./script/clean_repo_manifest.sh

# change all repo to ssh on all remote
.PHONY: repo_use_all_ssh
repo_use_all_ssh:
	./script/git_change_remote_https_to_git.py

# change all repo to https on all remote
.PHONY: repo_use_all_https
repo_use_all_https:
	./script/git_change_remote_https_to_git.py --git_to_https

###################
#  Configuration  #
###################
# generate new config.conf
.PHONY: config_install
config_install:
	./script/install_locally.sh

# generate config all repo
.PHONY: config_gen_all
config_gen_all:
	./script/git_repo_update_group.py
	./script/install_locally.sh

# generate config repo code_generator
.PHONY: config_gen_code_generator
config_gen_code_generator:
	./script/git_repo_update_group.py  --group base,code_generator
	./script/install_locally.sh

###################
#  Documentation  #
###################
# documentation all
.PHONY: doc
doc: doc_dev doc_migration doc_test doc_user

# documentation clean all
.PHONY: doc_clean
doc_clean: doc_clean_dev doc_clean_migration doc_clean_test doc_clean_user

# documentation dev
.PHONY: doc_dev
doc_dev:
	source ./.venv/bin/activate && make -C doc/itpp-labs_odoo-development/docs html || exit 1
	-$(BROWSER) doc/itpp-labs_odoo-development/docs/_build/html/index.html

.PHONY: doc_clean_dev
doc_clean_dev:
	make -C doc/itpp-labs_odoo-development/docs clean

# documentation migration
.PHONY: doc_migration
doc_migration:
	source ./.venv/bin/activate && make -C doc/itpp-labs_odoo-port-docs/docs html || exit 1
	-$(BROWSER) doc/itpp-labs_odoo-port-docs/docs/_build/html/index.html

.PHONY: doc_clean_migration
doc_clean_migration:
	make -C doc/itpp-labs_odoo-port-docs/docs clean

# documentation test
.PHONY: doc_test
doc_test:
	source ./.venv/bin/activate && make -C doc/itpp-labs_odoo-test-docs/doc-src html || exit 1
	-$(BROWSER) doc/itpp-labs_odoo-test-docs/doc-src/_build/html/index.html

.PHONY: doc_clean_test
doc_clean_test:
	make -C doc/itpp-labs_odoo-test-docs/doc-src clean

# documentation user
.PHONY: doc_user
doc_user:
	source ./.venv/bin/activate && make -C doc/odoo_documentation-user html || exit 1
	-$(BROWSER) doc/odoo_documentation-user/_build/html/index.html

.PHONY: doc_clean_user
doc_clean_user:
	make -C doc/odoo_documentation-user clean
