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

#########
#  RUN  #
#########
.PHONY: run
run:
	echo http://localhost:8069
	echo http://localhost:8069/web/database/manager
	./run.sh

.PHONY: run_test
run_test:
	echo http://localhost:8069
	./run.sh --database test

.PHONY: run_code_generator
run_code_generator:
	echo http://localhost:8069
	./run.sh --database code_generator

#############
#  INSTALL  #
#############
.PHONY: install_dev
install_dev:
	./script/install_locally_dev.sh

# Install this for the first time of dev environment
.PHONY: install_os
install_os:
	./script/install_dev.sh

.PHONY: install_docker_debian
install_docker_debian:
	./script/ install_debian_10_prod_docker.sh

.PHONY: install_docker_ubuntu
install_docker_ubuntu:
	./script/install_ubuntu_docker.sh

#####################
#  DB installation  #
#####################
.PHONY: db_list
db_list:
	./.venv/bin/python3 ./odoo/odoo-bin db --list

.PHONY: db_list_incompatible_database
db_list_incompatible_database:
	./.venv/bin/python3 ./odoo/odoo-bin db --list_incompatible_db

.PHONY: db_version
db_version:
	./.venv/bin/python3 ./odoo/odoo-bin db --version

.PHONY: db_drop_db_test
db_drop_db_test:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database test

.PHONY: db_drop_db_code_generator
db_drop_db_code_generator:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database code_generator

.PHONY: db_restore_erplibre_base_db_test
db_restore_erplibre_base_db_test:
	./.venv/bin/python3 ./odoo/odoo-bin db --restore --restore_image erplibre_base --database test

.PHONY: db_restore_erplibre_website_db_test
db_restore_erplibre_website_db_test:
	./.venv/bin/python3 ./odoo/odoo-bin db --restore --restore_image erplibre_website --database test

.PHONY: db_restore_erplibre_website_chat_crm_db_test
db_restore_erplibre_website_chat_crm_db_test:
	./.venv/bin/python3 ./odoo/odoo-bin db --restore --restore_image erplibre_website_chat_crm --database test

.PHONY: db_restore_erplibre_base_db_code_generator
db_restore_erplibre_base_db_code_generator:
	./.venv/bin/python3 ./odoo/odoo-bin db --restore --restore_image erplibre_base --database code_generator

#########################
#  Addons installation  #
#########################
.PHONY: addons_install_code_generator_demo
addons_install_code_generator_demo:
	./run.sh --no-http --stop-after-init -d code_generator -i code_generator_demo -u code_generator_demo

.PHONY: addons_uninstall_code_generator_demo
addons_uninstall_code_generator_demo:
	./run.sh --no-http --stop-after-init -d code_generator --uninstall code_generator_demo

.PHONY: addons_reinstall_code_generator_demo
addons_reinstall_code_generator_demo: addons_uninstall_code_generator_demo addons_install_code_generator_demo

.PHONY: addons_install_code_generator_demo_portal
addons_install_code_generator_demo_portal:
	./run.sh --no-http --stop-after-init -d code_generator -i code_generator_demo_portal -u code_generator_demo_portal

.PHONY: addons_uninstall_code_generator_demo_portal
addons_uninstall_code_generator_demo_portal:
	./run.sh --no-http --stop-after-init -d code_generator --uninstall code_generator_demo_portal
	./run.sh --no-http --stop-after-init -d code_generator --uninstall code_generator_demo

.PHONY: addons_reinstall_code_generator_demo_portal
addons_reinstall_code_generator_demo_portal: addons_uninstall_code_generator_demo_portal addons_install_code_generator_demo_portal

.PHONY: addons_install_demo_portal_on_code_generator
addons_install_demo_portal_on_code_generator:
	./run.sh --no-http --stop-after-init -d code_generator -i demo_portal -u demo_portal

.PHONY: addons_uninstall_demo_portal_on_code_generator
addons_uninstall_demo_portal_on_code_generator:
	./run.sh --no-http --stop-after-init -d code_generator --uninstall demo_portal

.PHONY: addons_reinstall_demo_portal_on_code_generator
addons_reinstall_demo_portal_on_code_generator: addons_uninstall_demo_portal_on_code_generator addons_install_demo_portal_on_code_generator

.PHONY: addons_install_demo_portal_on_test
addons_install_demo_portal_on_test:
	./run.sh --no-http --stop-after-init -d test -i demo_portal -u demo_portal

.PHONY: addons_uninstall_demo_portal_on_test
addons_uninstall_demo_portal_on_test:
	./run.sh --no-http --stop-after-init -d test --uninstall demo_portal

.PHONY: addons_reinstall_demo_portal_on_test
addons_reinstall_demo_portal_on_test: addons_uninstall_demo_portal_on_test addons_install_demo_portal_on_test

.PHONY: addons_install_all_code_generator_demo
addons_install_all_code_generator_demo:
	./run.sh --no-http --stop-after-init -d code_generator -i code_generator_demo -u code_generator_demo
	./run.sh --no-http --stop-after-init -d code_generator -i code_generator_demo_export_helpdesk -u code_generator_demo_export_helpdesk
	./run.sh --no-http --stop-after-init -d code_generator -i code_generator_demo_internal -u code_generator_demo_internal
	./run.sh --no-http --stop-after-init -d code_generator -i code_generator_demo_portal -u code_generator_demo_portal
	./run.sh --no-http --stop-after-init -d code_generator -i code_generator_demo_theme_website -u code_generator_demo_theme_website
	./run.sh --no-http --stop-after-init -d code_generator -i code_generator_demo_website_leaflet -u code_generator_demo_website_leaflet

.PHONY: addons_uninstall_all_code_generator_demo
addons_uninstall_all_code_generator_demo:
	./run.sh --no-http --stop-after-init -d code_generator --uninstall code_generator_demo,code_generator_demo_export_helpdesk,code_generator_demo_internal,code_generator_demo_portal,code_generator_demo_theme_website,code_generator_demo_website_leaflet

############
#  docker  #
############
# run docker
.PHONY: docker_run
docker_run:
	docker-compose up

.PHONY: docker_run_daemon
docker_run_daemon:
	docker-compose up -d

.PHONY: docker_stop
docker_stop:
	docker-compose down

.PHONY: docker_show_logs_live
docker_show_logs_live:
	docker-compose logs -f

.PHONY: docker_show_process
docker_show_process:
	docker-compose ps

.PHONY: docker_exec_erplibre
docker_exec_erplibre:
	docker exec -u root -ti erplibre_ERPLibre_1 bash

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
