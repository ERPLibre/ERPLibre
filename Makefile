SHELL := /bin/bash
LOG_FILE := ./.venv/make_test.log
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

.PHONY: run_prod_client
run_prod_client:
	echo http://localhost:8069
	./run.sh --database prod_client

.PHONY: run_code_generator
run_code_generator:
	echo http://localhost:8069
	# -$(BROWSER) http://localhost:8069
	./run.sh --database code_generator

.PHONY: run_parallel_cg
run_parallel_cg:
	parallel < ./conf/list_cg_test.txt

.PHONY: run_parallel_cg_template
run_parallel_cg_template:
	parallel < ./conf/list_cg_template_test.txt

.PHONY: run_parallel_cg_migrator
run_parallel_cg_migrator:
	parallel < ./conf/list_cg_migrator_test.txt

############
#  VERSION #
############
.PHONY: version
version:
	./script/version/update_env_version.py

#############
#  INSTALL  #
#############
.PHONY: install
install:install_os install_dev

.PHONY: install_dev
install_dev:
	#	./script/version/update_env_version.py
	#	./script/install/install_locally_dev.sh
	./script/version/update_env_version.py --install_dev

.PHONY: install_odoo_16
install_odoo_16:
	./script/version/update_env_version.py --erplibre_version odoo16.0_python3.10.14 --install_dev

.PHONY: switch_odoo_16
switch_odoo_16:
	./script/version/update_env_version.py --erplibre_version odoo16.0_python3.10.14 --switch
	./script/make.sh config_gen_all

.PHONY: install_odoo_14
install_odoo_14:
	./script/version/update_env_version.py --erplibre_version odoo14.0_python3.8.20 --install_dev

.PHONY: switch_odoo_14
switch_odoo_14:
	./script/version/update_env_version.py --erplibre_version odoo14.0_python3.8.20 --switch
	./script/make.sh config_gen_all

.PHONY: install_odoo_12
install_odoo_12:
	./script/version/update_env_version.py --erplibre_version odoo12.0_python3.7.17 --install_dev

.PHONY: switch_odoo_12
switch_odoo_12:
	./script/version/update_env_version.py --erplibre_version odoo12.0_python3.7.17 --switch
	./script/make.sh config_gen_all

.PHONY: install_odoo_all_version
install_odoo_all_version:
	./script/make.sh install_odoo_12
	./script/make.sh install_odoo_14
	./script/make.sh install_odoo_16

.PHONY: install_odoo_all_version_dev
install_odoo_all_version_dev:
	echo "Open Pycharm, close it before install Odoo and reopen at the end"
	pycharm .
	./script/make.sh install_odoo_12
	./script/make.sh install_odoo_14
	./script/make.sh install_odoo_16

#.PHONY: install_update_odoo
#install_update_odoo:
#	./script/version/update_env_version.py --install_dev --update_addons

.PHONY: install_show_version
install_show_version:
	./script/version/update_env_version.py -l

# Install this for the first time of dev environment
.PHONY: install_os
install_os:
	#./script/install/install_dev.sh
	./script/version/update_env_version.py --install

.PHONY: install_production
install_production:
	./script/install/install_dev.sh
	./script/install/install_production.sh

.PHONY: install_docker_debian
install_docker_debian:
	./script/install/install_debian_10_prod_docker.sh

.PHONY: install_docker_ubuntu
install_docker_ubuntu:
	./script/install/install_ubuntu_docker.sh

###################
#  Environnement  #
###################
.PHONY: pyenv_update
pyenv_update:
	~/.pyenv/bin/pyenv update

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
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database code_generator

.PHONY: db_drop_db_template
db_drop_db_template:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database template

.PHONY: db_drop_all
db_drop_all:
	./script/database/db_drop_all.py

.PHONY: db_drop_test
db_drop_test:
	./script/database/db_drop_all.py --test_only

.PHONY: db_clean_cache
db_clean_cache:
	./script/database/db_restore.py --clean_cache

.PHONY: db_restore_erplibre_base_db_test
db_restore_erplibre_base_db_test:
	./script/database/db_restore.py --database test

.PHONY: db_restore_erplibre_base_db_test_module_test
db_restore_erplibre_base_db_test_module_test:
	./script/database/db_restore.py --database test
	./script/addons/install_addons.sh test test

.PHONY: db_restore_prod_client
db_restore_prod_client:
	# You need to put the database backup in ./image_db/prod_client.zip
	./script/database/db_restore.py --database prod_client --image prod_client
	./script/database/migrate_prod_to_test.sh prod_client

.PHONY: db_restore_erplibre_base_db_test_image_test
db_restore_erplibre_base_db_test_image_test:
	./script/database/db_restore.py --database test --image test

.PHONY: db_restore_erplibre_website_db_test
db_restore_erplibre_website_db_test:
	./script/database/db_restore.py --database test --image erplibre_website

.PHONY: db_restore_erplibre_website_chat_crm_db_test
db_restore_erplibre_website_chat_crm_db_test:
	./script/database/db_restore.py --database test --image erplibre_website_chat_crm

.PHONY: db_restore_erplibre_ecommerce_base_db_test
db_restore_erplibre_ecommerce_base_db_test:
	./script/database/db_restore.py --database test --image erplibre_ecommerce_base

.PHONY: db_restore_erplibre_base_db_code_generator
db_restore_erplibre_base_db_code_generator:
	./script/database/db_restore.py --database code_generator

.PHONY: db_restore_erplibre_base_db_template
db_restore_erplibre_base_db_template:
	./script/database/db_restore.py --database template

.PHONY: db_create_db_test
db_create_db_test:
	./script/make.sh db_drop_db_test
	./.venv/bin/python3 ./odoo/odoo-bin db --create --database test

.PHONY: db_clone_test_to_test2
db_clone_test_to_test2:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database test2
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --database test2 --from_database test

.PHONY: db_test_export
db_test_export:
	./script/database/db_restore.py --database test_website_export
	./script/addons/install_addons_dev.sh test_website_export demo_website_data

.PHONY: db_test_re_export_website_attachments
db_test_re_export_website_attachments:
	./script/database/db_restore.py --database test_website_export
	./script/addons/install_addons_dev.sh test_website_export demo_website_attachments_data
	# TODO this test fail at uninstall, it remove all files.
	# TODO Strategy is to update ir_model_data, change module data and attach to another module like website
	# TODO and update all link in website, (or use id of ir.attachment instead of xmlid website.)
	./script/addons/uninstall_addons.sh test_website_export demo_website_attachments_data
	./script/addons/install_addons_dev.sh test_website_export code_generator_demo_export_website_attachments

########################
#  Image installation  #
########################

.PHONY: image_db_create_erplibre_code_generator
image_db_create_erplibre_code_generator:
	./script/make.sh addons_install_code_generator_basic
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database code_generator --restore_image erplibre_code_generator_basic
	./script/make.sh addons_install_code_generator_featured
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database code_generator --restore_image erplibre_code_generator_featured
	./script/make.sh addons_install_code_generator_full
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database code_generator --restore_image erplibre_code_generator_full

.PHONY: image_db_create_all_parallel
image_db_create_all_parallel:
	./script/database/db_restore.py --clean_cache
	echo "Search in-existing module"
	./.venv/bin/python3 ./script/database/image_db.py --check_addons_exist
	echo "Create Image DB"
	./.venv/bin/python3 ./script/database/image_db.py --generate_bash_cmd_parallel | bash
	./script/database/db_restore.py --clean_cache
	#./script/make.sh image_db_create_test_website_attachments

.PHONY: image_db_list_data
image_db_list_data:
	./.venv/bin/python3 ./script/database/image_db.py --generate_bash_cmd_parallel
	#./.venv/bin/python3 ./script/database/image_db.py --generate_bash_cmd_parallel --odoo_version 12.0

.PHONY: image_db_list
image_db_list:
	./.venv/bin/python3 ./script/database/image_db.py --show_list_only
	#./.venv/bin/python3 ./script/database/image_db.py --generate_bash_cmd_parallel --odoo_version 12.0

.PHONY: image_db_create_test_website_attachments
image_db_create_test_website_attachments:
	./script/database/db_restore.py --database code_generator_test_website_attachements --image test_website_attachments
	# Do your stuff
	./.venv/bin/python3 ./odoo/odoo-bin --limit-time-real 999999 --no-http -c config.conf --stop-after-init -d code_generator_test_website_attachements -u all
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database code_generator_test_website_attachements --restore_image test_website_attachments

.PHONY: image_diff_base_website
image_diff_base_website:
	#./script/database/compare_backup.py --backup_file_1 ./image_db/erplibre_base.zip --backup_file_2 ./image_db/erplibre_website.zip
	./script/database/compare_backup.py --backup_1 odoo12.0_base --backup_2 odoo12.0_website

#########################
#  Addons installation  #
#########################
.PHONY: addons_install_code_generator_basic
addons_install_code_generator_basic:
	./script/database/db_restore.py --database code_generator
	./script/addons/install_addons_dev.sh code_generator code_generator

.PHONY: addons_install_code_generator_featured
addons_install_code_generator_featured:
	./script/database/db_restore.py --database code_generator
	./script/addons/install_addons_dev.sh code_generator code_generator_cron,code_generator_hook,code_generator_portal

.PHONY: addons_install_code_generator_full
addons_install_code_generator_full:
	./script/database/db_restore.py --database code_generator
	./script/addons/install_addons_dev.sh code_generator code_generator_cron,code_generator_hook,code_generator_portal,code_generator_db_servers,code_generator_website_snippet,code_generator_geoengine,code_generator_theme_website,code_generator_website_leaflet

.PHONY: addons_install_code_generator_demo
addons_install_code_generator_demo:
	./script/database/db_restore.py --database code_generator
	./script/addons/install_addons_dev.sh code_generator code_generator_demo

.PHONY: addons_install_all_code_generator_demo
addons_install_all_code_generator_demo:
	./script/database/db_restore.py --database code_generator
	# TODO ignore code_generator_demo_internal cause (demo_internal, demo_model_2_internal_view_form) already exists
	./script/addons/install_addons_dev.sh code_generator code_generator_demo,code_generator_demo_export_helpdesk,code_generator_demo_export_website,code_generator_demo_internal_inherit,code_generator_demo_portal,code_generator_demo_theme_website,code_generator_demo_website_leaflet,code_generator_demo_website_snippet,code_generator_auto_backup
	# Conflict between code_generator_demo_website_multiple_snippet and code_generator_demo_internal_inherit
	./script/database/db_restore.py --database code_generator
	./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_multiple_snippet
	./script/database/db_restore.py --database code_generator_test_website_attachements --image test_website_attachments
	./script/addons/install_addons_dev.sh code_generator_test_website_attachements code_generator_demo_export_website_attachments

	#./script/addons/install_addons_dev.sh code_generator code_generator_demo
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_export_helpdesk
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_export_website
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_internal
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_internal_inherit
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_portal
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_theme_website
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_leaflet
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_snippet
	#./script/addons/install_addons_dev.sh code_generator code_generator_demo_website_multiple_snippet
	#./script/addons/install_addons_dev.sh code_generator code_generator_auto_backup

.PHONY: addons_install_all_code_generator_template
addons_install_all_code_generator_template:
	./script/database/db_restore.py --database template
	./script/addons/install_addons_dev.sh template demo_portal,auto_backup,demo_internal_inherit
	./script/addons/install_addons_dev.sh template code_generator_template_demo_portal,code_generator_template_demo_sysadmin_cron,code_generator_template_demo_internal_inherit

	#./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_portal -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_portal
	#./script/addons/install_addons_dev.sh template demo_portal
	#./script/addons/install_addons_dev.sh template code_generator_template_demo_portal

	#./script/code_generator/search_class_model.py --quiet -d addons/OCA_server-tools/auto_backup -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_sysadmin_cron
	#./script/addons/install_addons_dev.sh template auto_backup
	#./script/addons/install_addons_dev.sh template code_generator_template_demo_sysadmin_cron

	#./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_internal -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_internal
	#./script/addons/install_addons_dev.sh template demo_internal
	#./script/addons/install_addons_dev.sh template code_generator_template_demo_internal

	#./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_internal_inherit -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_internal_inherit
	#./script/addons/install_addons_dev.sh template demo_internal_inherit
	#./script/addons/install_addons_dev.sh template code_generator_template_demo_internal_inherit

	# TODO not working, need to add in test parallel
	#./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_website_snippet -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_website_snippet
	#./script/addons/install_addons_dev.sh template demo_website_snippet
	#./script/addons/install_addons_dev.sh template code_generator_template_demo_website_snippet

	# TODO not working, need to add in test parallel
	#./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_website_multiple_snippet -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_website_multiple_snippet
	#./script/addons/install_addons_dev.sh template demo_website_multiple_snippet
	#./script/addons/install_addons_dev.sh template code_generator_template_demo_website_multiple_snippet

.PHONY: addons_install_all_generated_demo
addons_install_all_generated_demo:
	./script/database/db_restore.py --database template
	./script/addons/install_addons_dev.sh template demo_helpdesk_data,demo_website_data,demo_internal,demo_internal_inherit,demo_portal,demo_website_leaflet,demo_website_snippet,auto_backup
	./script/addons/install_addons_theme.sh template theme_website_demo_code_generator
	#./script/addons/install_addons_dev.sh template demo_helpdesk_data
	#./script/addons/install_addons_dev.sh template demo_website_data
	#./script/addons/install_addons_dev.sh template demo_internal
	#./script/addons/install_addons_dev.sh template demo_internal_inherit
	#./script/addons/install_addons_dev.sh template demo_portal
	#./script/addons/install_addons_dev.sh template demo_website_leaflet
	#./script/addons/install_addons_dev.sh template demo_website_snippet
	#./script/addons/install_addons_dev.sh template auto_backup
	#./script/addons/install_addons_theme.sh template theme_website_demo_code_generator

##################
# Code generator #
##################
.PHONY: addons_install_code_generator_template_code_generator
addons_install_code_generator_template_code_generator:
	./script/database/db_restore.py --database template
	./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator/code_generator -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_code_generator --with_inherit
	./script/maintenance/black.sh ./addons/TechnoLibre_odoo-code-generator-template/code_generator_template_code_generator
	./script/addons/install_addons_dev.sh template code_generator
	./script/addons/install_addons_dev.sh template code_generator_template_code_generator
	./script/git/remote_code_generation_git_compare.py --quiet --git_gui --clear --replace_directory --directory1 ./addons/TechnoLibre_odoo-code-generator-template/code_generator_code_generator --directory2 ./addons/TechnoLibre_odoo-code-generator/code_generator_code_generator

.PHONY: addons_install_code_generator_code_generator
addons_install_code_generator_code_generator:
	./script/database/db_restore.py --database code_generator
	./script/addons/install_addons_dev.sh code_generator code_generator_code_generator
	./script/git/remote_code_generation_git_compare.py --quiet --git_gui  --clear --replace_directory --directory1 ./addons/TechnoLibre_odoo-code-generator/code_generator --directory2 ./addons/TechnoLibre_odoo-code-generator-template/code_generator

.PHONY: meld_code_generator_template_code_generator
meld_code_generator_template_code_generator:
	./script/make.sh clean
	meld ./addons/TechnoLibre_odoo-code-generator/code_generator_code_generator ./addons/TechnoLibre_odoo-code-generator-template/code_generator_code_generator

.PHONY: meld_code_generator_code_generator
meld_code_generator_code_generator:
	./script/make.sh clean
	meld ./addons/TechnoLibre_odoo-code-generator-template/code_generator ./addons/TechnoLibre_odoo-code-generator/code_generator

########################
#  Extra migrator sql  #
########################
.PHONY: addons_install_code_generator_mariadb_sql_example_1
addons_install_code_generator_mariadb_sql_example_1:
	./script/database/restore_mariadb_sql_example_1.sh
	./script/database/db_restore.py --database code_generator
	./script/addons/install_addons_dev.sh code_generator code_generator_portal
	./script/addons/install_addons_dev.sh code_generator code_generator_migrator_demo_mariadb_sql_example_1

	./script/database/db_restore.py --database template
	./script/addons/install_addons_dev.sh template code_generator_portal,demo_mariadb_sql_example_1
	./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_mariadb_sql_example_1 -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_mariadb_sql_example_1
	./script/addons/install_addons_dev.sh template code_generator_template_demo_mariadb_sql_example_1

	./script/database/db_restore.py --database code_generator
	./script/addons/install_addons_dev.sh code_generator code_generator_portal
	./script/addons/install_addons_dev.sh code_generator code_generator_demo_mariadb_sql_example_1

##########
#  test  #
##########
.PHONY: test
test:
	./script/make.sh clean
	-rm ${LOG_FILE}
	./script/make.sh test_base |& tee -a ${LOG_FILE}
	./script/test/check_result_test.sh ${LOG_FILE}

.PHONY: test_full
test_full:
	./script/make.sh clean
	-rm ${LOG_FILE}
	./script/make.sh test_base |& tee -a ${LOG_FILE}
	./script/make.sh test_extra |& tee -a ${LOG_FILE}
	#./script/make.sh doc |& tee -a ${LOG_FILE}
	./script/test/check_result_test.sh ${LOG_FILE}

.PHONY: test_full_fast
test_full_fast:
	./script/make.sh clean
	# Need to create a BD to create cache _cache_erplibre_base
	./script/database/db_restore.py --database test
	#./script/test/run_parallel_test.py --keep_cache
	./script/test/run_parallel_test.py
	# TODO This test is broken in parallel
	#./script/make.sh test_code_generator_hello_world

.PHONY: test_full_fast_debug
test_full_fast_debug:
	./script/make.sh clean
	# Need to create a BD to create cache _cache_erplibre_base
	./script/database/db_restore.py --database test
	./script/test/run_parallel_test.py --keep_cache
	# TODO This test is broken in parallel
	#./script/make.sh test_code_generator_hello_world

.PHONY: test_full_fast_coverage
test_full_fast_coverage:
	./script/make.sh clean
	# Need to create a BD to create cache _cache_erplibre_base
	./script/database/db_restore.py --database test
	./.venv/bin/coverage erase
	./script/test/run_parallel_test.py --coverage
	# TODO This test is broken in parallel
	#./script/make.sh test_coverage_code_generator_hello_world
	./.venv/bin/coverage combine -a
	./.venv/bin/coverage report -m --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage html --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage json --include="addons/TechnoLibre_odoo-code-generator/*"
	# run: make open_test_coverage


.PHONY: test_cg_demo
test_cg_demo:
	./script/make.sh clean
	# Need to create a BD to create cache _cache_erplibre_base
	./script/database/db_restore.py --database test
	./.venv/bin/coverage erase
	./script/addons/coverage_install_addons_dev.sh test code_generator_demo
	./.venv/bin/coverage combine -a
	./.venv/bin/coverage report -m --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage html --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage json --include="addons/TechnoLibre_odoo-code-generator/*"


.PHONY: test_base
test_base:
	./script/make.sh test_format
	./script/make.sh test_code_generator_hello_world
	./script/make.sh test_installation_demo
	./script/make.sh test_code_generator_generation
	./script/make.sh test_code_generator_generation_template

.PHONY: test_extra
test_extra:
	./script/make.sh test_code_generator_migrator_demo_mariadb_sql_example_1
	./script/make.sh test_code_generator_template_demo_mariadb_sql_example_1
	./script/make.sh test_code_generator_demo_mariadb_sql_example_1

.PHONY: test_format
test_format:
	./script/maintenance/black.sh --check ./addons/TechnoLibre_odoo-code-generator/
	./script/maintenance/black.sh --check ./addons/TechnoLibre_odoo-code-generator-template/

.PHONY: test_code_generator_hello_world
test_code_generator_hello_world:
	./test/code_generator/hello_world.sh

.PHONY: test_coverage_code_generator_hello_world
test_coverage_code_generator_hello_world:
	./test/code_generator/coverage_hello_world.sh

.PHONY: test_installation_demo
test_installation_demo:
	./script/code_generator/check_git_change_code_generator.sh ./addons/TechnoLibre_odoo-code-generator-template
	./script/database/db_restore.py --database test_demo
	./script/addons/install_addons.sh test_demo demo_helpdesk_data,demo_internal,demo_internal_inherit,demo_mariadb_sql_example_1,demo_portal,demo_website_data,demo_website_leaflet,demo_website_snippet
	./script/addons/install_addons_theme.sh test_demo theme_website_demo_code_generator

.PHONY: test_code_generator_generation
test_code_generator_generation:
	./script/code_generator/check_git_change_code_generator.sh ./addons/TechnoLibre_odoo-code-generator-template
	./script/code_generator/check_git_change_code_generator.sh ./addons/OCA_server-tools/auto_backup
	# Multiple
	./script/database/db_restore.py --database test_code_generator
	./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo,code_generator_demo_export_helpdesk,code_generator_demo_export_website,code_generator_demo_internal,code_generator_demo_portal,code_generator_demo_theme_website,code_generator_demo_website_leaflet,code_generator_demo_website_snippet ./addons/TechnoLibre_odoo-code-generator-template code_generator_demo,demo_helpdesk_data,demo_website_data,demo_internal,demo_portal,theme_website_demo_code_generator,demo_website_leaflet,demo_website_snippet
	# inherit
	# TODO should be in multiple list, need to support it
	./script/database/db_restore.py --database test_code_generator
	./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_internal_inherit ./addons/TechnoLibre_odoo-code-generator-template demo_internal_inherit
	# auto_backup
	./script/database/db_restore.py --database test_code_generator
	./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_auto_backup ./addons/OCA_server-tools/auto_backup auto_backup

	# Single
	#./script/database/db_restore.py --database test_code_generator
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo ./addons/TechnoLibre_odoo-code-generator-template code_generator_demo
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_export_helpdesk ./addons/TechnoLibre_odoo-code-generator-template demo_helpdesk_data
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_export_website ./addons/TechnoLibre_odoo-code-generator-template demo_website_data
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_internal ./addons/TechnoLibre_odoo-code-generator-template demo_internal
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_portal ./addons/TechnoLibre_odoo-code-generator-template demo_portal
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_theme_website ./addons/TechnoLibre_odoo-code-generator-template theme_website_demo_code_generator
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_website_leaflet ./addons/TechnoLibre_odoo-code-generator-template demo_website_leaflet
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_website_snippet ./addons/TechnoLibre_odoo-code-generator-template demo_website_snippet
	#./script/database/db_restore.py --database test_code_generator
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_internal_inherit ./addons/TechnoLibre_odoo-code-generator-template demo_internal_inherit
	#./script/database/db_restore.py --database test_code_generator
	#./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_auto_backup ./addons/OCA_server-tools/auto_backup auto_backup

.PHONY: test_code_generator_generation_template
test_code_generator_generation_template:
	./script/make.sh test_code_generator_code_template_demo_portal
	./script/make.sh test_code_generator_code_template_demo_internal_inherit
	./script/make.sh test_code_generator_code_template_demo_sysadmin_cron

.PHONY: test_code_generator_code_template_demo_portal
test_code_generator_code_template_demo_portal:
	./script/code_generator/check_git_change_code_generator.sh ./addons/TechnoLibre_odoo-code-generator-template
	./script/database/db_restore.py --database test_template
	./script/addons/install_addons_dev.sh test_template demo_portal
	#./script/addons/install_addons_dev.sh test_template code_generator_template_demo_portal
	./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_portal -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_portal --with_inherit
	./script/code_generator/install_and_test_code_generator.sh test_template code_generator_template_demo_portal ./addons/TechnoLibre_odoo-code-generator-template code_generator_demo_portal

.PHONY: test_code_generator_code_template_demo_internal_inherit
test_code_generator_code_template_demo_internal_inherit:
	./script/code_generator/check_git_change_code_generator.sh ./addons/TechnoLibre_odoo-code-generator-template
	./script/database/db_restore.py --database test_template
	./script/addons/install_addons_dev.sh test_template demo_internal_inherit
	#./script/addons/install_addons_dev.sh test_template code_generator_template_demo_internal_inherit
	./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_internal_inherit -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_internal_inherit --with_inherit
	./script/code_generator/install_and_test_code_generator.sh test_template code_generator_template_demo_internal_inherit ./addons/TechnoLibre_odoo-code-generator-template code_generator_demo_internal_inherit

.PHONY: test_code_generator_code_template_demo_sysadmin_cron
test_code_generator_code_template_demo_sysadmin_cron:
	./script/code_generator/check_git_change_code_generator.sh ./addons/OCA_server-tools/auto_backup
	./script/database/db_restore.py --database test_template
	./script/addons/install_addons_dev.sh test_template auto_backup
	#./script/addons/install_addons_dev.sh test_template code_generator_template_demo_sysadmin_cron
	./script/code_generator/search_class_model.py --quiet -d addons/OCA_server-tools/auto_backup -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_sysadmin_cron --with_inherit
	./script/code_generator/install_and_test_code_generator.sh test_template code_generator_template_demo_sysadmin_cron ./addons/TechnoLibre_odoo-code-generator-template code_generator_auto_backup

.PHONY: test_code_generator_migrator_demo_mariadb_sql_example_1
test_code_generator_migrator_demo_mariadb_sql_example_1:
	./script/code_generator/check_git_change_code_generator.sh ./addons/TechnoLibre_odoo-code-generator-template
	./script/database/restore_mariadb_sql_example_1.sh
	./script/database/db_restore.py --database test_code_generator
	./script/addons/install_addons_dev.sh test_code_generator code_generator_portal
	#./script/addons/install_addons_dev.sh test_code_generator code_generator_migrator_demo_mariadb_sql_example_1
	./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_migrator_demo_mariadb_sql_example_1 ./addons/TechnoLibre_odoo-code-generator-template demo_mariadb_sql_example_1

.PHONY: test_code_generator_template_demo_mariadb_sql_example_1
test_code_generator_template_demo_mariadb_sql_example_1:
	./script/code_generator/check_git_change_code_generator.sh ./addons/TechnoLibre_odoo-code-generator-template
	./script/database/db_restore.py --database test_template
	./script/addons/install_addons_dev.sh test_template code_generator_portal,demo_mariadb_sql_example_1
	./script/code_generator/search_class_model.py --quiet -d addons/TechnoLibre_odoo-code-generator-template/demo_mariadb_sql_example_1 -t addons/TechnoLibre_odoo-code-generator-template/code_generator_template_demo_mariadb_sql_example_1 --with_inherit
	#./script/addons/install_addons_dev.sh test_template code_generator_template_demo_mariadb_sql_example_1
	./script/code_generator/install_and_test_code_generator.sh test_template code_generator_template_demo_mariadb_sql_example_1 ./addons/TechnoLibre_odoo-code-generator-template code_generator_demo_mariadb_sql_example_1

.PHONY: test_code_generator_demo_mariadb_sql_example_1
test_code_generator_demo_mariadb_sql_example_1:
	./script/code_generator/check_git_change_code_generator.sh ./addons/TechnoLibre_odoo-code-generator-template
	./script/database/db_restore.py --database test_code_generator
	./script/addons/install_addons_dev.sh test_code_generator code_generator_portal
	#./script/addons/install_addons_dev.sh test_code_generator code_generator_demo_mariadb_sql_example_1
	./script/code_generator/install_and_test_code_generator.sh test_code_generator code_generator_demo_mariadb_sql_example_1 ./addons/TechnoLibre_odoo-code-generator-template demo_mariadb_sql_example_1

###############
# Test addons #
###############
.PHONY: test_addons_sale
test_addons_sale:
	./.venv/bin/coverage erase
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database test_addons_sale
	./test.sh -d test_addons_sale --db-filter test_addons_sale -i sale
	./.venv/bin/coverage combine -a
	./.venv/bin/coverage report -m
	./.venv/bin/coverage html
	./.venv/bin/coverage json

.PHONY: test_addons_helpdesk
test_addons_helpdesk:
	./.venv/bin/coverage erase
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database test_addons_helpdesk
	./test.sh -d test_addons_helpdesk --db-filter test_addons_helpdesk -i helpdesk_mgmt
	./.venv/bin/coverage combine -a
	./.venv/bin/coverage report -m
	./.venv/bin/coverage html
	./.venv/bin/coverage json

.PHONY: test_addons_code_generator
test_addons_code_generator:
	./.venv/bin/coverage erase
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database test_addons_code_generator
	# TODO missing test in code_generator
	./test.sh --dev cg -d test_addons_code_generator --db-filter test_addons_code_generator -i code_generator
	./.venv/bin/coverage combine -a
	./.venv/bin/coverage report -m --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage html --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage json --include="addons/TechnoLibre_odoo-code-generator/*"
	# run: make open_test_coverage

.PHONY: test_addons_code_generator_code_generator
test_addons_code_generator_code_generator:
	# TODO this test only generation, not test
	./.venv/bin/coverage erase
	./script/database/db_restore.py --database test_addons_code_generator_code_generator
	./test.sh --dev cg -d test_addons_code_generator_code_generator --db-filter test_addons_code_generator_code_generator -i code_generator_code_generator
	./.venv/bin/coverage combine -a
	./.venv/bin/coverage report -m --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage html --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage json --include="addons/TechnoLibre_odoo-code-generator/*"
	# run: make open_test_coverage

.PHONY: test_addons_code_generator_template_code_generator
test_addons_code_generator_template_code_generator:
	# TODO this test only generation, not test
	./.venv/bin/coverage erase
	./script/database/db_restore.py --database test_addons_code_generator_template_code_generator
	./test.sh --dev cg -d test_addons_code_generator_template_code_generator --db-filter test_addons_code_generator_template_code_generator -i code_generator
	./test.sh --dev cg -d test_addons_code_generator_template_code_generator --db-filter test_addons_code_generator_template_code_generator -i code_generator_template_code_generator
	./.venv/bin/coverage combine -a
	./.venv/bin/coverage report -m --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage html --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv/bin/coverage json --include="addons/TechnoLibre_odoo-code-generator/*"
	# run: make open_test_coverage

.PHONY: open_test_coverage
open_test_coverage:
	-$(BROWSER) htmlcov/index.html

# TODO load specific test file : ./run.sh -d test_file --log-level=test --test-enable --stop-after-init --test-file ./.venv/test.py

#########
#  tag  #
#########
.PHONY: tag_push_all
tag_push_all:
	./script/git/tag_push_all.py

##############
#  terminal  #
##############
.PHONY: open_terminal
open_terminal:
	./script/open_terminal_code_generator.sh

############
#  format  #
############
.PHONY: format
format:
	parallel ::: "./script/make.sh format_code_generator" "./script/make.sh format_code_generator_template" "./script/make.sh format_script" "./script/make.sh format_erplibre_addons" "./script/make.sh format_supported_addons"

.PHONY: format_code_generator
format_code_generator:
	.venv/bin/isort --profile black -l 79 ./addons/TechnoLibre_odoo-code-generator/
	./script/maintenance/black.sh ./addons/TechnoLibre_odoo-code-generator/
	./script/maintenance/prettier_xml.sh ./addons/TechnoLibre_odoo-code-generator/

.PHONY: format_erplibre_addons
format_erplibre_addons:
	.venv/bin/isort --profile black -l 79 ./addons/ERPLibre_erplibre_addons/
	./script/maintenance/black.sh ./addons/ERPLibre_erplibre_addons/
	./script/maintenance/prettier_xml.sh ./addons/ERPLibre_erplibre_addons/
	.venv/bin/isort --profile black -l 79 ./addons/ERPLibre_erplibre_theme_addons/
	./script/maintenance/black.sh ./addons/ERPLibre_erplibre_theme_addons/
	#./script/maintenance/prettier_xml.sh ./addons/ERPLibre_erplibre_theme_addons/

.PHONY: format_supported_addons
format_supported_addons:
	.venv/bin/isort --profile black -l 79 ./addons/MathBenTech_erplibre-family-management/
	./script/maintenance/black.sh ./addons/MathBenTech_erplibre-family-management/
	#./script/maintenance/prettier_xml.sh ./addons/MathBenTech_erplibre-family-management/
	.venv/bin/isort --profile black -l 79 ./addons/MathBenTech_odoo-business-spending-management-quebec-canada/
	./script/maintenance/black.sh ./addons/MathBenTech_odoo-business-spending-management-quebec-canada/
	#./script/maintenance/prettier_xml.sh ./addons/MathBenTech_erplibre-family-management/

.PHONY: format_code_generator_template
format_code_generator_template:
	.venv/bin/isort --profile black -l 79 ./addons/TechnoLibre_odoo-code-generator-template/
	./script/maintenance/black.sh ./addons/TechnoLibre_odoo-code-generator-template/
	#./script/maintenance/prettier_xml.sh ./addons/TechnoLibre_odoo-code-generator-template/

.PHONY: format_script
format_script:
	#.venv/bin/isort --profile black -l 79 ./script/ --gitignore
	./script/maintenance/black.sh ./script/

.PHONY: format_script_isort_only
format_script_isort_only:
	.venv/bin/isort --profile black -l 79 ./script/ --gitignore

#########
#  log  #
#########
.PHONY: log_show_test
log_show_test:
	vim ${LOG_FILE}

##########
# poetry #
##########
.PHONY: poetry_update
poetry_update:
	./script/poetry/poetry_update.py

###########
#  clean  #
###########
.PHONY: clean_code_generator_template
clean_code_generator_template:
	./script/git/repo_revert_git_diff_date_from_code_generator.py

.PHONY: clean_test
clean_test:
	cd addons/OCA_server-tools; git stash; git clean -fd

############
#  docker  #
############
# run docker
.PHONY: docker_run
docker_run:
	docker compose up

.PHONY: docker_run_daemon
docker_run_daemon:
	docker compose up -d

.PHONY: docker_stop
docker_stop:
	docker compose down

.PHONY: docker_restart_daemon
docker_restart_daemon:
	./script/make.sh docker_stop
	./script/make.sh docker_run_daemon

.PHONY: docker_show_databases
docker_show_databases:
	./script/docker/docker_list_database.sh

.PHONY: docker_show_logs_live
docker_show_logs_live:
	docker compose logs -f

.PHONY: docker_show_process
docker_show_process:
	docker compose ps

.PHONY: docker_exec_erplibre
docker_exec_erplibre:
	./script/docker/docker_exec.sh

.PHONY: docker_exec_erplibre_gen_config
docker_exec_erplibre_gen_config:
	./script/docker/docker_gen_config.sh

.PHONY: docker_exec_erplibre_make_test
docker_exec_erplibre_make_test:
	./script/docker/docker_make_test.sh

.PHONY: docker_exec_erplibre_repo_show_status
docker_exec_erplibre_repo_show_status:
	./script/docker/docker_repo_show_status.sh

# build docker
.PHONY: docker_build_odoo_16
docker_build_odoo_16:
	./script/docker/docker_build.sh --odoo_16

.PHONY: docker_build_odoo_14
docker_build_odoo_14:
	./script/docker/docker_build.sh --odoo_14

.PHONY: docker_build_odoo_12
docker_build_odoo_12:
	./script/docker/docker_build.sh --odoo_12

# build docker release
.PHONY: docker_build_release
docker_build_release:
	./script/docker/docker_build.sh --release

# build docker release alpha
.PHONY: docker_build_release_alpha
docker_build_release_alpha:
	./script/docker/docker_build.sh --release_alpha

# build docker release beta
.PHONY: docker_build_release_beta
docker_build_release_beta:
	./script/docker/docker_build.sh --release_beta

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
	./script/git/clean_repo_manifest.sh

# configure all repo
.PHONY: repo_configure_all
repo_configure_all:
	./script/manifest/update_manifest_local_dev.sh

# configure only group code_generator
.PHONY: repo_configure_group_code_generator
repo_configure_group_code_generator:
	./script/manifest/update_manifest_local_dev_code_generator.sh

# Show git status for all repo
.PHONY: repo_show_status
repo_show_status:
	./.venv/repo forall -pc "git status -s"

# Show divergence between actual repository and production manifest
.PHONY: repo_diff_manifest_production
repo_diff_manifest_production:
	./script/git/git_show_code_diff_repo_manifest.py

# Show git diff for all repo from last tag version release
.PHONY: repo_diff_from_last_version
repo_diff_from_last_version:
	./script/git/repo_diff_last_version.sh

# Show git diff statistique for all repo from last tag version release
.PHONY: repo_diff_stat_from_last_version
repo_diff_stat_from_last_version:
	./script/git/repo_diff_stat_last_version.sh

# change all repo to ssh on all remote
.PHONY: repo_use_all_ssh
repo_use_all_ssh:
	./script/git/git_change_remote_https_to_git.py

# change all repo to https on all remote
.PHONY: repo_use_all_https
repo_use_all_https:
	./script/git/git_change_remote_https_to_git.py --git_to_https

###################
#  Configuration  #
###################
# generate new config.conf
.PHONY: config_install
config_install:
	./script/generate_config.sh

.PHONY: config_update
config_update:
	./run.sh -c config.conf -s --stop-after-init

.PHONY: config_update_over_proxy
config_update_over_proxy:
	./run.sh -c config.conf -s --stop-after-init --max-cron-threads 2 --workers 2 --xmlrpc-interface 127.0.0.1 --proxy-mode

.PHONY: config_update_dev
config_update_dev:
	./run.sh -c config.conf -s --stop-after-init --max-cron-threads 4 --workers 4

.PHONY: config_update_dev_mono
config_update_dev_mono:
	./run.sh -c config.conf -s --stop-after-init --workers 0

.PHONY: config_clear
config_clear:
	rm -f ./config.conf

# generate config all repo
.PHONY: config_gen_all
config_gen_all:
	echo "config_gen_all"
	./script/git/git_repo_update_group.py
	./script/generate_config.sh

# generate config repo code_generator
.PHONY: config_gen_code_generator
config_gen_code_generator:
	./script/git/git_repo_update_group.py --group base,code_generator
	./script/generate_config.sh

# generate config repo image_db
.PHONY: config_gen_image_db
config_gen_image_db:
	./script/git/git_repo_update_group.py --group base,image_db
	./script/generate_config.sh

##########
#  I18n  #
##########

# i18n generation demo_portal
.PHONY: i18n_generate_demo_portal
i18n_generate_demo_portal:
	./.venv/bin/python3 ./odoo/odoo-bin i18n --database code_generator --module demo_portal --addons_path addons/TechnoLibre_odoo-code-generator

###########
#  Clean  #
###########

.PHONY: clean
clean:
	find . -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete

###############
#  Statistic  #
###############
.PHONY: stat_module_evolution_per_year
stat_module_evolution_per_year:
	./script/statistic/show_evolution_module.py --before_date "2016-01-01" --more_year 7

.PHONY: stat_module_evolution_per_year_OCA
stat_module_evolution_per_year_OCA:
	./script/statistic/show_evolution_module.py --filter "/OCA/" --before_date "2016-01-01" --more_year 7

###################
#  Documentation  #
###################
# documentation all
.PHONY: doc
doc:
#	./script/make.sh doc_dev
#	./script/make.sh doc_migration
#	./script/make.sh doc_test
#	./script/make.sh doc_user
#	./script/make.sh doc_markdown
	parallel ::: "./script/make.sh doc_dev" "./script/make.sh doc_migration" "./script/make.sh doc_test" "./script/make.sh doc_user" "./script/make.sh doc_markdown"

# documentation clean all
.PHONY: doc_clean
doc_clean:
	./script/make.sh doc_clean_dev
	./script/make.sh doc_clean_migration
	./script/make.sh doc_clean_test
	./script/make.sh doc_clean_user

# open documentation all
.PHONY: open_doc_all
open_doc_all:
	./script/make.sh open_doc_dev
	./script/make.sh open_doc_migration
	./script/make.sh open_doc_test
	./script/make.sh open_doc_user

# documentation dev
.PHONY: doc_dev
doc_dev:
	source ./.venv/bin/activate && make -C doc/itpp-labs_odoo-development/docs html || exit 1

.PHONY: open_doc_dev
open_doc_dev:
	-$(BROWSER) doc/itpp-labs_odoo-development/docs/_build/html/index.html

.PHONY: doc_clean_dev
doc_clean_dev:
	make -C doc/itpp-labs_odoo-development/docs clean

# documentation migration
.PHONY: doc_migration
doc_migration:
	source ./.venv/bin/activate && make -C doc/itpp-labs_odoo-port-docs/docs html || exit 1

.PHONY: open_doc_migration
open_doc_migration:
	-$(BROWSER) doc/itpp-labs_odoo-port-docs/docs/_build/html/index.html

.PHONY: doc_clean_migration
doc_clean_migration:
	make -C doc/itpp-labs_odoo-port-docs/docs clean

# documentation test
.PHONY: doc_test
doc_test:
	source ./.venv/bin/activate && make -C doc/itpp-labs_odoo-test-docs/doc-src html || exit 1

.PHONY: open_doc_test
open_doc_test:
	-$(BROWSER) doc/itpp-labs_odoo-test-docs/doc-src/_build/html/index.html

.PHONY: doc_clean_test
doc_clean_test:
	make -C doc/itpp-labs_odoo-test-docs/doc-src clean

# documentation user
.PHONY: doc_user
doc_user:
	ln -sf ../../odoo/odoo ./doc/odoo_documentation-user/odoo
	source ./.venv/bin/activate && make -C doc/odoo_documentation-user html || exit 1

.PHONY: open_doc_user
open_doc_user:
	-$(BROWSER) doc/odoo_documentation-user/_build/html/index.html

.PHONY: doc_clean_user
doc_clean_user:
	make -C doc/odoo_documentation-user clean

# documentation markdown
.PHONY: doc_markdown
doc_markdown:
	./.venv/bin/mmg --verbose --yes ./doc/CODE_GENERATOR.base.md

# Cache
.PHONY: clear_cache
clear_cache:
	rm -rf cache artifacts .coverage coverage.json

#######
# IDE #
#######
.PHONY: pycharm_open
pycharm_open:
	~/.local/share/JetBrains/Toolbox/scripts/pycharm .

.PHONY: pycharm_configure
pycharm_configure:
	./script/ide/pycharm_configuration.py --init

