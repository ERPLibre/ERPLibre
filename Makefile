SHELL := /bin/bash
LOG_FILE := ./.venv.$(cat ".erplibre-version" | xargs)/make_test.log
#############
#  General  #
#############
# ALL
.PHONY: all
all: todo

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

# Include all Makefile
-include ./conf/make.code_generator.Makefile
-include ./conf/make.erplibre.Makefile
-include ./conf/make.database.Makefile
-include ./conf/make.docker.Makefile
-include ./conf/make.documentation.Makefile
-include ./conf/make.image_db.Makefile
-include ./conf/make.installation.Makefile
-include ./conf/make.installation.poetry.Makefile
-include ./conf/make.test.Makefile
-include ./conf/make.todo.Makefile

# Include private Makefile
-include ./private/make.private.Makefile

# Example for update
.PHONY: custom_run_example
custom_run_example:
	./run.sh -d example_prod

.PHONY: custom_update_example
custom_update_example:
	./script/database/db_restore.py --database example_prod --image image_name_to_restore
	./script/addons/update_addons_all.sh example_prod
	./script/addons/update_prod_to_dev.sh example_prod

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

############
#  VERSION #
############
.PHONY: version
version:
	./script/version/update_env_version.py

###################
#  Environnement  #
###################
.PHONY: pyenv_update
pyenv_update:
	~/.pyenv/bin/pyenv update

.PHONY: db_create_db_test
db_create_db_test:
	./script/make.sh db_drop_db_test
	./odoo_bin.sh db --create --database test

.PHONY: db_clone_test_to_test2
db_clone_test_to_test2:
	./odoo_bin.sh db --drop --database test2
	./odoo_bin.sh db --clone --database test2 --from_database test

.PHONY: db_test_export
db_test_export:
	./script/database/db_restore.py --database test_website_export
	./script/addons/install_addons_dev.sh test_website_export demo_website_data

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

##############
#  selenium  #
##############
.PHONY: open_selenium
open_selenium:
	./.venv.erplibre/bin/python ./script/selenium/web_login.py

############
#  format  #
############
.PHONY: format
format:
	./script/maintenance/format_file_to_commit.py

.PHONY: format_all
format_all:
	parallel ::: "./script/make.sh format_code_generator" "./script/make.sh format_code_generator_template" "./script/make.sh format_script" "./script/make.sh format_erplibre_addons" "./script/make.sh format_supported_addons"

.PHONY: format_code_generator
format_code_generator:
	.venv.erplibre/bin/isort --profile black -l 79 ./addons/TechnoLibre_odoo-code-generator/
	./script/maintenance/black.sh ./addons/TechnoLibre_odoo-code-generator/
	./script/maintenance/prettier_xml.sh ./addons/TechnoLibre_odoo-code-generator/

.PHONY: format_erplibre_addons
format_erplibre_addons:
	.venv.erplibre/bin/isort --profile black -l 79 ./addons/ERPLibre_erplibre_addons/
	./script/maintenance/black.sh ./addons/ERPLibre_erplibre_addons/
	./script/maintenance/prettier_xml.sh ./addons/ERPLibre_erplibre_addons/
	.venv.erplibre/bin/isort --profile black -l 79 ./addons/ERPLibre_erplibre_theme_addons/
	./script/maintenance/black.sh ./addons/ERPLibre_erplibre_theme_addons/
	#./script/maintenance/prettier_xml.sh ./addons/ERPLibre_erplibre_theme_addons/

.PHONY: format_supported_addons
format_supported_addons:
	.venv.erplibre/bin/isort --profile black -l 79 ./addons/MathBenTech_erplibre-family-management/
	./script/maintenance/black.sh ./addons/MathBenTech_erplibre-family-management/
	#./script/maintenance/prettier_xml.sh ./addons/MathBenTech_erplibre-family-management/
	.venv.erplibre/bin/isort --profile black -l 79 ./addons/MathBenTech_odoo-business-spending-management-quebec-canada/
	./script/maintenance/black.sh ./addons/MathBenTech_odoo-business-spending-management-quebec-canada/
	#./script/maintenance/prettier_xml.sh ./addons/MathBenTech_erplibre-family-management/

.PHONY: format_code_generator_template
format_code_generator_template:
	.venv.erplibre/bin/isort --profile black -l 79 ./addons/TechnoLibre_odoo-code-generator-template/
	./script/maintenance/black.sh ./addons/TechnoLibre_odoo-code-generator-template/
	#./script/maintenance/prettier_xml.sh ./addons/TechnoLibre_odoo-code-generator-template/

.PHONY: format_script
format_script:
	#.venv.erplibre/bin/isort --profile black -l 79 ./script/ --gitignore
	./script/maintenance/black.sh ./script/

.PHONY: format_script_isort_only
format_script_isort_only:
	.venv.erplibre/bin/isort --profile black -l 79 ./script/ --gitignore

#########
#  log  #
#########
.PHONY: log_show_test
log_show_test:
	vim ${LOG_FILE}

###########
#  clean  #
###########
.PHONY: clean_code_generator_template
clean_code_generator_template:
	./script/git/repo_revert_git_diff_date_from_code_generator.py

.PHONY: clean_test
clean_test:
	cd addons/OCA_server-tools; git stash; git clean -fd

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
	.venv.erplibre/bin/repo forall -pc "git status -s"

# Show git stash for all repo
.PHONY: repo_do_stash
repo_do_stash:
	.venv.erplibre/bin/repo forall -pc "git stash"

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
	# Need http to configure the file config.conf, or will disable it
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

# generate config repo image_db
.PHONY: config_gen_image_db
config_gen_image_db:
	./script/git/git_repo_update_group.py --group base,image_db
	./script/generate_config.sh

.PHONY: config_gen_migration
config_gen_migration:
	./script/git/git_repo_update_group.py --group base,addons,migration
	./script/generate_config.sh

##########
#  I18n  #
##########

# i18n generation demo_portal
.PHONY: i18n_generate_demo_portal
i18n_generate_demo_portal:
	./odoo_bin.sh i18n --database code_generator --module demo_portal --addons_path addons/TechnoLibre_odoo-code-generator

###########
#  Clean  #
###########

.PHONY: clean
clean:
	find . \( -name '__pycache__' -type d -prune -o -name '*.pyc' -o -name '*.pyo' \) -exec rm -rf {} +

###############
#  Statistic  #
###############
.PHONY: stat_module_evolution_per_year
stat_module_evolution_per_year:
	./script/statistic/show_evolution_module.py --before_date "2016-01-01" --more_year 7

.PHONY: stat_module_evolution_per_year_OCA
stat_module_evolution_per_year_OCA:
	./script/statistic/show_evolution_module.py --filter "/OCA/" --before_date "2016-01-01" --more_year 7

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
