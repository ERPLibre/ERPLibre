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

.PHONY: db_drop_db_test2
db_drop_db_test2:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database test2

.PHONY: db_drop_db_test3
db_drop_db_test3:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database test3

.PHONY: db_drop_db_code_generator
db_drop_db_code_generator:
	time ./.venv/bin/python3 ./odoo/odoo-bin db --drop --database code_generator

.PHONY: db_drop_db_template
db_drop_db_template:
	time ./.venv/bin/python3 ./odoo/odoo-bin db --drop --database template

.PHONY: db_restore_erplibre_base_db_test
db_restore_erplibre_base_db_test:
	time ./script/db_restore.py --database test

.PHONY: db_restore_erplibre_base_db_test2
db_restore_erplibre_base_db_test2:
	time ./script/db_restore.py --database test2

.PHONY: db_restore_erplibre_base_db_test3
db_restore_erplibre_base_db_test3:
	time ./script/db_restore.py --database test3

.PHONY: db_restore_erplibre_website_db_test
db_restore_erplibre_website_db_test:
	time ./script/db_restore.py --database test --image erplibre_website

.PHONY: db_restore_erplibre_website_chat_crm_db_test
db_restore_erplibre_website_chat_crm_db_test:
	time ./script/db_restore.py --database test --image erplibre_website_chat_crm

.PHONY: db_restore_erplibre_ecommerce_base_db_test
db_restore_erplibre_ecommerce_base_db_test:
	time ./script/db_restore.py --database test --image erplibre_ecommerce_base

.PHONY: db_restore_erplibre_base_db_code_generator
db_restore_erplibre_base_db_code_generator:
	time ./script/db_restore.py --database code_generator

.PHONY: db_restore_erplibre_base_db_template
db_restore_erplibre_base_db_template:
	time ./script/db_restore.py --database template

#########################
#  Addons installation  #
#########################
.PHONY: addons_install_code_generator_demo
addons_install_code_generator_demo:
	./install_addon.sh code_generator code_generator_demo

.PHONY: addons_uninstall_code_generator_demo
addons_uninstall_code_generator_demo:
	./uninstall_addon.sh code_generator code_generator_demo

.PHONY: addons_reinstall_code_generator_demo
addons_reinstall_code_generator_demo: addons_uninstall_code_generator_demo addons_install_code_generator_demo

.PHONY: addons_install_all_code_generator_demo
addons_install_all_code_generator_demo:
	./install_addon.sh code_generator code_generator_demo
	./install_addon.sh code_generator code_generator_demo_export_helpdesk
	./install_addon.sh code_generator code_generator_demo_internal
	./install_addon.sh code_generator code_generator_demo_portal
	./install_addon.sh code_generator code_generator_demo_theme_website
	./install_addon.sh code_generator code_generator_demo_website_leaflet
	./install_addon.sh code_generator code_generator_demo_website_snippet

.PHONY: addons_install_all_code_generator_template
addons_install_all_code_generator_template:
	./install_addon.sh template demo_portal,auto_backup
	./install_addon.sh template code_generator_template_demo_portal
	./install_addon.sh template code_generator_template_demo_sysadmin_cron

.PHONY: addons_install_all_generated_demo
addons_install_all_generated_demo:
	./install_addon.sh template demo_export_helpdesk,demo_internal,demo_portal,demo_website_leaflet,demo_website_snippet
	# TODO support installation theme with cli
	#./install_addon.sh template theme_website_demo_code_generator

.PHONY: addons_install_all_code_generator
addons_install_all_code_generator:
	./install_addon.sh code_generator code_generator_auto_backup

##########
#  test  #
##########
.PHONY: test_code_generator_generation
test_code_generator_generation: db_restore_erplibre_base_db_code_generator addons_install_all_code_generator_demo

.PHONY: test_code_generator_template
test_code_generator_template: db_restore_erplibre_base_db_template addons_install_all_code_generator_template

.PHONY: test_code_generator_demo
test_code_generator_demo: db_restore_erplibre_base_db_template addons_install_all_generated_demo

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

# configure all repo
.PHONY: repo_configure_all
repo_configure_all:
	./script/update_manifest_local_dev.sh

# configure only group code_generator
.PHONY: repo_configure_group_code_generator
repo_configure_group_code_generator:
	./script/update_manifest_local_dev_code_generator.sh

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
	./script/git_repo_update_group.py --group base,code_generator
	./script/install_locally.sh

##########
#  I18n  #
##########

# i18n generation demo_portal
.PHONY: i18n_generate_demo_portal
i18n_generate_demo_portal:
	./.venv/bin/python3 ./odoo/odoo-bin i18n --database code_generator --module demo_portal --addons_path addons/TechnoLibre_odoo-code-generator

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
