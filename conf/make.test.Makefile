########
# TEST #
########

# TODO load specific test file : ./run.sh -d test_file --log-level=test --test-enable --stop-after-init --test-file ./.venv/test.py

.PHONY: open_test_coverage
open_test_coverage:
	-$(BROWSER) htmlcov/index.html

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

.PHONY: test_installation_demo
test_installation_demo:
	./script/code_generator/check_git_change_code_generator.sh ./addons/TechnoLibre_odoo-code-generator-template
	./script/database/db_restore.py --database test_demo
	./script/addons/install_addons.sh test_demo demo_helpdesk_data,demo_internal,demo_internal_inherit,demo_mariadb_sql_example_1,demo_portal,demo_website_data,demo_website_leaflet,demo_website_snippet
	./script/addons/install_addons_theme.sh test_demo theme_website_demo_code_generator

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