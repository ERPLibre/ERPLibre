##################
# CODE GENERATOR #
##################

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

.PHONY: db_restore_erplibre_base_db_code_generator
db_restore_erplibre_base_db_code_generator:
	./script/database/db_restore.py --database code_generator

.PHONY: db_restore_erplibre_base_db_template
db_restore_erplibre_base_db_template:
	./script/database/db_restore.py --database template

.PHONY: db_drop_db_code_generator
db_drop_db_code_generator:
	./odoo_bin.sh db --drop --database code_generator

.PHONY: db_drop_db_template
db_drop_db_template:
	./odoo_bin.sh db --drop --database template

.PHONY: db_test_re_export_website_attachments
db_test_re_export_website_attachments:
	./script/database/db_restore.py --database test_website_export
	./script/addons/install_addons_dev.sh test_website_export demo_website_attachments_data
	# TODO this test fail at uninstall, it remove all files.
	# TODO Strategy is to update ir_model_data, change module data and attach to another module like website
	# TODO and update all link in website, (or use id of ir.attachment instead of xmlid website.)
	./script/addons/uninstall_addons.sh test_website_export demo_website_attachments_data
	./script/addons/install_addons_dev.sh test_website_export code_generator_demo_export_website_attachments

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
#  TEST  #
##########
.PHONY: test_code_generator_hello_world
test_code_generator_hello_world:
	./test/code_generator/hello_world.sh

.PHONY: test_coverage_code_generator_hello_world
test_coverage_code_generator_hello_world:
	./test/code_generator/coverage_hello_world.sh

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

.PHONY: test_addons_code_generator
test_addons_code_generator:
	./.venv.erplibre/bin/coverage erase
	./odoo_bin.sh db --drop --database test_addons_code_generator
	# TODO missing test in code_generator
	./test.sh --dev cg -d test_addons_code_generator --db-filter test_addons_code_generator -i code_generator
	./.venv.erplibre/bin/coverage combine -a
	./.venv.erplibre/bin/coverage report -m --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv.erplibre/bin/coverage html --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv.erplibre/bin/coverage json --include="addons/TechnoLibre_odoo-code-generator/*"
	# run: make open_test_coverage

.PHONY: test_addons_code_generator_code_generator
test_addons_code_generator_code_generator:
	# TODO this test only generation, not test
	./.venv.erplibre/bin/coverage erase
	./script/database/db_restore.py --database test_addons_code_generator_code_generator
	./test.sh --dev cg -d test_addons_code_generator_code_generator --db-filter test_addons_code_generator_code_generator -i code_generator_code_generator
	./.venv.erplibre/bin/coverage combine -a
	./.venv.erplibre/bin/coverage report -m --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv.erplibre/bin/coverage html --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv.erplibre/bin/coverage json --include="addons/TechnoLibre_odoo-code-generator/*"
	# run: make open_test_coverage

.PHONY: test_addons_code_generator_template_code_generator
test_addons_code_generator_template_code_generator:
	# TODO this test only generation, not test
	./.venv.erplibre/bin/coverage erase
	./script/database/db_restore.py --database test_addons_code_generator_template_code_generator
	./test.sh --dev cg -d test_addons_code_generator_template_code_generator --db-filter test_addons_code_generator_template_code_generator -i code_generator
	./test.sh --dev cg -d test_addons_code_generator_template_code_generator --db-filter test_addons_code_generator_template_code_generator -i code_generator_template_code_generator
	./.venv.erplibre/bin/coverage combine -a
	./.venv.erplibre/bin/coverage report -m --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv.erplibre/bin/coverage html --include="addons/TechnoLibre_odoo-code-generator/*"
	./.venv.erplibre/bin/coverage json --include="addons/TechnoLibre_odoo-code-generator/*"
	# run: make open_test_coverage

# generate config repo code_generator
.PHONY: config_gen_code_generator
config_gen_code_generator:
	./script/git/git_repo_update_group.py --group base,code_generator
	./script/generate_config.sh