SHELL := /bin/bash
LOG_FILE := ./.venv/make_test.log
#############
#  General  #
#############
# ALL
.PHONY: all
all: doc

#########
# Robot #
#########
.PHONY: robot_libre_all
robot_libre_all:
	echo "Install all for robot_libre"
	./script/make.sh robot_libre_init
	./script/make.sh robot_libre_pre
	OPEN_DASHBOARD=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops,erplibre_devops_me,erplibre_devops_extra

.PHONY: robot_libre_init
robot_libre_init:
	echo "Robot Libre init"
	echo "Sorry for your lost data"
	echo "Generate repository"
	./script/manifest/update_manifest_local_dev.sh "-g base,image_db,code_generator"
	echo "Generate new fast configuration repo"
	./script/git/git_repo_update_group.py --group base,code_generator
	echo "Generate configuration"
	./script/generate_config.sh
	./script/git/git_change_remote_https_to_git.py

.PHONY: robot_libre_pre
robot_libre_pre:
	echo "Create database robotlibre"
	./script/database/db_restore.py --database robotlibre

.PHONY: robot_libre
robot_libre:
	./script/make.sh robot_libre_pre
	echo "Install devops"
	./script/addons/install_addons_dev.sh robotlibre erplibre_devops
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database robotlibre --restore_image robotlibre_last

.PHONY: robot_libre_fast
robot_libre_fast:
	echo "FAST! RobotLibre"
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database _cache_robotlibre_last
	./script/database/db_restore.py --database robotlibre --image robotlibre_last

.PHONY: robot_libre_fast_update
robot_libre_fast_update:
	echo "FAST! RobotLibre with update"
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database _cache_robotlibre_last
	./script/database/db_restore.py --database robotlibre --image robotlibre_last
	./script/addons/install_addons_dev.sh robotlibre erplibre_devops

.PHONY: robot_libre_extra
robot_libre_extra:
	./script/make.sh robot_libre_pre
	echo "Install erplibre_devops and erplibre_devops_extra"
	./script/addons/install_addons_dev.sh robotlibre erplibre_devops,erplibre_devops_extra
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database robotlibre --restore_image robotlibre_last

.PHONY: robot_libre_me
robot_libre_me:
	./script/make.sh robot_libre_pre
	echo "Install erplibre_devops, erplibre_devops_me and erplibre_devops_extra"
	OPEN_DASHBOARD=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops,erplibre_devops_me,erplibre_devops_extra
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database robotlibre --restore_image robotlibre_last

.PHONY: robot_libre_me_only
robot_libre_me_only:
	./script/make.sh robot_libre
	IS_ONLY_ME=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops_me
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database robotlibre --restore_image robotlibre_last

.PHONY: robot_libre_me_auto
robot_libre_me_auto:
	./script/make.sh robot_libre
	IS_ME_AUTO=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops_me

.PHONY: robot_libre_me_auto_force
robot_libre_me_auto_force:
	./script/make.sh robot_libre
	IS_ME_AUTO_FORCE=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops_me

.PHONY: robot_libre_me_only_auto_force
robot_libre_me_only_auto_force:
	./script/make.sh robot_libre
	IS_ONLY_ME=TRUE IS_ME_AUTO_FORCE=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops_me

.PHONY: robot_libre_update
robot_libre_update:
	./run.sh --limit-time-real 999999 --no-http --stop-after-init --dev cg -d robotlibre -i erplibre_devops -u erplibre_devops

.PHONY: robot_libre_run
robot_libre_run:
	./run.sh -d robotlibre

.PHONY: robot_libre_open
robot_libre_open:
	./.venv/bin/python ./script/selenium/web_login.py --open_me_devops

.PHONY: robot_libre_format
robot_libre_format:
	parallel ::: "./script/maintenance/format.sh ./addons/ERPLibre_erplibre_addons/erplibre_devops" "./script/maintenance/format.sh ./addons/ERPLibre_erplibre_addons/erplibre_devops_me"

.PHONY: robot_libre_generate
robot_libre_generate:
	./script/code_generator/new_project.py -f -d ./addons/ERPLibre_erplibre_addons -m erplibre_devops

.PHONY: run_db
run_db:
	./run.sh -d $(bd)

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

#############
#  INSTALL  #
#############
.PHONY: install
install:install_os install_dev

.PHONY: install_dev
install_dev:
	./script/install/install_locally_dev.sh

# Install this for the first time of dev environment
.PHONY: install_os
install_os:
	./script/install/install_dev.sh

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

.PHONY: db_restore_erplibre_base_db_test2
db_restore_erplibre_base_db_test2:
	./script/database/db_restore.py --database test2

.PHONY: db_restore_erplibre_base_db_test3
db_restore_erplibre_base_db_test3:
	./script/database/db_restore.py --database test3

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
.PHONY: image_db_create_erplibre_base
image_db_create_erplibre_base:
	.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_base
	.venv/bin/python3 ./odoo/odoo-bin db --create --database image_creation_erplibre_base
	./script/addons/install_addons_from_file.sh image_creation_erplibre_base ./conf/module_list_image_erplibre_base.txt
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_base --restore_image erplibre_base

.PHONY: image_db_create_erplibre_website
image_db_create_erplibre_website:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_website
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_website

	./script/addons/install_addons.sh image_creation_erplibre_website website,erplibre_website_snippets_basic_html,erplibre_website_snippets_cards,erplibre_website_snippets_structures,erplibre_website_snippets_timelines,website_form_builder,muk_website_branding,website_snippet_anchor,website_anchor_smooth_scroll,website_snippet_all
	./script/addons/install_addons_theme.sh image_creation_erplibre_website theme_default
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_website --restore_image erplibre_website

	./script/addons/install_addons.sh image_creation_erplibre_website crm,website_crm,crm_team_quebec
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_website --restore_image erplibre_website_crm

	./script/addons/install_addons.sh image_creation_erplibre_website website_livechat
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_website --restore_image erplibre_website_chat_crm

	./script/addons/install_addons.sh image_creation_erplibre_website website_sale,erplibre_base_quebec,website_snippet_product_category,website_snippet_carousel_product
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_website --restore_image erplibre_ecommerce_base

	./script/addons/install_addons.sh image_creation_erplibre_website stock,purchase,website_sale_management
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_website --restore_image erplibre_ecommerce_advance

	./script/addons/install_addons.sh image_creation_erplibre_website project
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_website --restore_image erplibre_ecommerce_project

	./script/addons/install_addons.sh image_creation_erplibre_website pos_sale,muk_pos_branding
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_website --restore_image erplibre_ecommerce_pos

	./script/addons/install_addons.sh image_creation_erplibre_website hr
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_website --restore_image erplibre_ecommerce_pos_hr

.PHONY: image_db_create_erplibre_demo
image_db_create_erplibre_demo:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_demo
	./.venv/bin/python3 ./odoo/odoo-bin db --create --database image_creation_demo --demo
	./script/addons/install_addons_from_file.sh image_creation_demo ./conf/module_list_image_erplibre_base.txt
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_demo --restore_image erplibre_demo_base
	./script/addons/install_addons.sh image_creation_demo website,erplibre_website_snippets_basic_html,erplibre_website_snippets_cards,erplibre_website_snippets_structures,erplibre_website_snippets_timelines,website_form_builder,muk_website_branding,website_snippet_anchor,website_anchor_smooth_scroll,website_snippet_all,crm,website_crm,crm_team_quebec,website_livechat,website_sale,erplibre_base_quebec,website_snippet_product_category,website_snippet_carousel_product,stock,purchase,website_sale_management,project,pos_sale,muk_pos_branding,hr
	./script/addons/install_addons_theme.sh image_creation_demo theme_default
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_demo --restore_image erplibre_demo_full

.PHONY: image_db_create_erplibre_code_generator
image_db_create_erplibre_code_generator:
	./script/make.sh addons_install_code_generator_basic
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database code_generator --restore_image erplibre_code_generator_basic
	./script/make.sh addons_install_code_generator_featured
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database code_generator --restore_image erplibre_code_generator_featured
	./script/make.sh addons_install_code_generator_full
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database code_generator --restore_image erplibre_code_generator_full

.PHONY: image_db_create_erplibre_package_accounting
image_db_create_erplibre_package_accounting:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_accounting
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_accounting
	./script/addons/install_addons.sh image_creation_erplibre_package_accounting erplibre_base_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_accounting account_fiscal_year_closing,account_export_csv,account_financial_report,account_tax_balance,mis_builder_cash_flow,partner_statement,account_bank_statement_import_camt_oca,account_bank_statement_import_move_line,account_bank_statement_import_ofx,account_bank_statement_import_online,account_bank_statement_import_online_paypal,account_bank_statement_import_online_transferwise,account_bank_statement_import_paypal,account_bank_statement_import_split,account_bank_statement_import_txt_xlsx,accounting_pdf_reports,om_account_accountant,om_account_asset,om_account_budget
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_accounting --restore_image erplibre_package_accounting

.PHONY: image_db_create_erplibre_package_business_requirements
image_db_create_erplibre_package_business_requirements:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_business_requirements
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_business_requirements
	./script/addons/install_addons.sh image_creation_erplibre_package_business_requirements crm_team_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_business_requirements business_requirement,business_requirement_crm,business_requirement_deliverable,business_requirement_sale,business_requirement_sale_timesheet
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_business_requirements --restore_image erplibre_package_business_requirements

.PHONY: image_db_create_erplibre_package_contract
image_db_create_erplibre_package_contract:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_contract
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_contract
	./script/addons/install_addons.sh image_creation_erplibre_package_contract agreement,agreement_account,agreement_legal,agreement_legal_sale,agreement_project,agreement_sale,agreement_serviceprofile,agreement_stock,contract,contract_forecast,contract_invoice_start_end_dates,contract_layout_category_hide_detail,contract_mandate,contract_payment_mode,contract_sale,contract_sale_invoicing,contract_sale_mandate,contract_sale_payment_mode,contract_transmit_method,contract_variable_qty_prorated,contract_variable_qty_timesheet,contract_variable_quantity,product_contract,product_contract_variable_quantity
#	./script/addons/install_addons.sh image_creation agreement_legal_sale_fieldservice,agreement_maintenance,agreement_mrp,agreement_repair
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_contract --restore_image erplibre_package_contract

.PHONY: image_db_create_erplibre_package_crm
image_db_create_erplibre_package_crm:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_crm
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_crm
	./script/addons/install_addons.sh image_creation_erplibre_package_crm erplibre_base_quebec,crm_team_quebec,crm,crm_livechat,crm_phone_validation,crm_project,crm_reveal
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_crm --restore_image erplibre_package_crm

.PHONY: image_db_create_erplibre_package_e_commerce
image_db_create_erplibre_package_e_commerce:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_e_commerce
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_e_commerce
	./script/addons/install_addons.sh image_creation_erplibre_package_e_commerce erplibre_base_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_e_commerce website_sale,website_sale_comparison,website_sale_delivery,website_sale_digital,website_sale_link_tracker,website_sale_management,website_sale_stock,website_sale_wishlist,website_sale_attribute_filter_category,website_sale_attribute_filter_order,website_sale_attribute_filter_price,website_sale_cart_selectable,website_sale_category_description,website_sale_checkout_skip_payment,website_sale_exception,website_sale_hide_empty_category,website_sale_hide_price,website_sale_product_attachment,website_sale_product_attribute_filter_visibility,website_sale_product_attribute_value_filter_existing,website_sale_product_detail_attribute_image,website_sale_product_detail_attribute_value_image,website_sale_product_minimal_price,website_sale_product_reference_displayed,website_sale_product_sort,website_sale_product_style_badge,website_sale_require_legal,website_sale_require_login,website_sale_secondary_unit,website_sale_show_company_data,website_sale_stock_available,website_sale_stock_available_display,website_sale_stock_force_block,website_sale_suggest_create_account,website_sale_wishlist_keep,website_snippet_carousel_product,website_snippet_product_category,product_rating_review,product_configurator,product_configurator_mrp,product_configurator_purchase,product_configurator_sale,product_configurator_stock,website_product_configurator
	./script/addons/install_addons_theme.sh image_creation_erplibre_package_e_commerce theme_default
#	./script/addons/install_addons.sh image_creation website_sale_product_brand,website_sale_tax_toggle,website_sale_vat_required,product_configurator_sale_mrp,product_configurator_stock_lots,product_configurator_subconfig,website_product_configurator_mrp
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_e_commerce --restore_image erplibre_package_e_commerce

.PHONY: image_db_create_erplibre_package_field_service
image_db_create_erplibre_package_field_service:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_field_service
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_field_service
	./script/addons/install_addons.sh image_creation_erplibre_package_field_service erplibre_base_quebec,crm_team_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_field_service fieldservice,fieldservice_account,fieldservice_account_analytic,fieldservice_account_payment,fieldservice_activity,fieldservice_agreement,fieldservice_change_management,fieldservice_crm,fieldservice_delivery,fieldservice_distribution,fieldservice_fleet,fieldservice_geoengine,fieldservice_isp_account,fieldservice_isp_flow,fieldservice_location_builder,fieldservice_maintenance,fieldservice_partner_multi_relation,fieldservice_project,fieldservice_purchase,fieldservice_recurring,fieldservice_repair,fieldservice_route,fieldservice_route_account,fieldservice_route_stock,fieldservice_route_vehicle,fieldservice_sale,fieldservice_sale_recurring,fieldservice_sale_stock,fieldservice_size,fieldservice_skill,fieldservice_stage_server_action,fieldservice_stage_validation,fieldservice_stock,fieldservice_stock_account,fieldservice_stock_account_analytic,fieldservice_substatus,fieldservice_vehicle,fieldservice_vehicle_stock
#	./script/addons/install_addons.sh image_creation fieldservice_google_map,fieldservice_google_marker_icon_picker
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_field_service --restore_image erplibre_package_field_service

.PHONY: image_db_create_erplibre_package_helpdesk
image_db_create_erplibre_package_helpdesk:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_helpdesk
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_helpdesk
	./script/addons/install_addons.sh image_creation_erplibre_package_helpdesk helpdesk_mgmt,helpdesk_mgmt_project,helpdesk_motive,helpdesk_type,helpdesk_mgmt_timesheet,helpdesk_mgmt_timesheet_time_control,helpdesk_mgmt_partner_sequence,helpdesk_mgmt_sla
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_helpdesk --restore_image erplibre_package_helpdesk

.PHONY: image_db_create_erplibre_package_hr
image_db_create_erplibre_package_hr:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_hr
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_hr
	./script/addons/install_addons.sh image_creation_erplibre_package_hr erplibre_base_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_hr hr,hr_expense_associate_with_customer,hr_expense_tip,res_partner_fix_group_by_company,hr_attendance,hr_contract,hr_expense,hr_expense_check,hr_gamification,hr_holidays,hr_maintenance,hr_org_chart,hr_payroll,hr_payroll_account,hr_recruitment,hr_recruitment_survey,hr_timesheet,hr_timesheet_attendance,hr_attendance_autoclose,hr_attendance_geolocation,hr_attendance_modification_tracking,hr_attendance_reason,hr_attendance_report_theoretical_time,hr_attendance_rfid,hr_calendar_rest_time,hr_contract_currency,hr_contract_document,hr_contract_multi_job,hr_contract_rate,hr_course,hr_employee_age,hr_employee_birth_name,hr_employee_calendar_planning,hr_employee_display_own_info,hr_employee_document,hr_employee_emergency_contact,hr_employee_firstname,hr_employee_health,hr_employee_id,hr_employee_language,hr_employee_medical_examination,hr_employee_partner_external,hr_employee_phone_extension,hr_employee_relative,hr_employee_service,hr_employee_service_contract,hr_employee_social_media,hr_employee_ssn,hr_expense_advance_clearing,hr_expense_cancel,hr_expense_invoice,hr_expense_payment_difference,hr_expense_petty_cash,hr_expense_sequence,hr_expense_tier_validation,hr_experience,hr_holidays_accrual_advanced,hr_holidays_credit,hr_holidays_hour,hr_holidays_leave_auto_approve,hr_holidays_leave_repeated,hr_holidays_leave_request_wizard,hr_holidays_length_validation,hr_holidays_notify_employee_manager,hr_holidays_public,hr_holidays_settings,hr_holidays_validity_date,hr_job_category,hr_payroll_cancel,hr_payslip_change_state,hr_period,hr_skill,hr_worked_days_from_timesheet,resource_hook,hr_contract_single_open,hr_contract_wage_type,hr_employee_private_wizard,hr_employee_type,hr_employee_type_private_wizard,hr_event,hr_expense_same_month,hr_working_space,muk_hr_utils
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_hr --restore_image erplibre_package_hr

.PHONY: image_db_create_erplibre_package_project
image_db_create_erplibre_package_project:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_project
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_project
	./script/addons/install_addons.sh image_creation_erplibre_package_project erplibre_base_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_project project,project_chatter,project_default_task_stage,project_form_with_dates,project_hide_create_sale_order,project_iteration,project_iteration_parent_only,project_iteration_parent_type_required,project_portal_hide_timesheets,project_portal_parent_task,project_remaining_hours_update,project_stage,project_stage_allow_timesheet,project_stage_no_quick_create,project_task_date_planned,project_task_deadline_from_project,project_task_full_text_search,project_task_id_in_display_name,project_task_link,project_task_reference,project_task_resource_type,project_task_search_parent_subtask,project_task_stage_external_mail,project_task_subtask_same_project,project_task_type,project_template,project_template_numigi,project_template_timesheet,project_type,project_time_budget,project_time_range
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_project --restore_image erplibre_package_project

.PHONY: image_db_create_erplibre_package_purchase
image_db_create_erplibre_package_purchase:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_purchase
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_purchase
	./script/addons/install_addons.sh image_creation_erplibre_package_purchase erplibre_base_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_purchase purchase,purchase_mrp,purchase_requisition,purchase_stock,product_supplier_info_helpers,purchase_consignment,purchase_consignment_delivery_expense,purchase_consignment_inventory,purchase_consignment_inventory_line_domain,purchase_estimated_time_arrival,purchase_invoice_empty_lines,purchase_invoice_from_picking,purchase_partner_products,purchase_warning_minimum_amount
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_purchase --restore_image erplibre_package_purchase

.PHONY: image_db_create_erplibre_package_sale
image_db_create_erplibre_package_sale:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_sale
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_sale
	./script/addons/install_addons.sh image_creation_erplibre_package_sale erplibre_base_quebec,crm_team_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_sale sale,sale_crm,sale_expense,sale_management,sale_margin,sale_mrp,sale_purchase,sale_quotation_builder,sale_stock,sale_timesheet,sales_team,product_create_group,product_dimension,product_dimension_numigi,product_extra_views,product_extra_views_purchase,product_extra_views_sale,product_extra_views_stock,product_kit,product_panel_shortcut,product_reference,product_reference_list_view,product_variant_button_complete_form,sale_order_line_limit,sale_degroup_tax,payment,payment_transfer,purchase,stock
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_sale --restore_image erplibre_package_sale

.PHONY: image_db_create_erplibre_package_scrummer
image_db_create_erplibre_package_scrummer:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_scrummer
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_scrummer
	./script/addons/install_addons.sh image_creation_erplibre_package_scrummer erplibre_base_quebec
	./script/addons/install_addons.sh image_creation_erplibre_package_scrummer scrummer,scrummer_git,scrummer_kanban,scrummer_scrum,scrummer_timesheet_category,scrummer_workflow_security,scrummer_workflow_transition_by_project,scrummer_workflow_transitions_by_task_type,web_diagram_position,web_syncer,web_widget_image_url,project_agile_sale_timesheet,project_agile_analytic,project_agile_scrum,project_git_github,project_git_gitlab,project_portal
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_scrummer --restore_image erplibre_package_scrummer

.PHONY: image_db_create_erplibre_package_stock
image_db_create_erplibre_package_stock:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_stock
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_stock
	./script/addons/install_addons.sh image_creation_erplibre_package_stock stock,stock_account,stock_dropshipping,stock_landed_costs,stock_picking_batch,purchase_warehouse_access,stock_component,stock_component_account,stock_inventory_accounting_date_editable,stock_inventory_category_domain,stock_inventory_internal_location,stock_inventory_line_domain,stock_location_position_alphanum,stock_picking_change_destination,stock_serial_single_quant,stock_theorical_quantity_access,stock_turnover_rate,stock_warehouse_access,stock_warehouse_distance
#	./script/addons/install_addons.sh image_creation_erplibre_package_stock stock_zebra,stock_inventory_line_domain_barcode
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_stock --restore_image erplibre_package_stock

.PHONY: image_db_create_erplibre_package_timesheet
image_db_create_erplibre_package_timesheet:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_timesheet
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_timesheet
	./script/addons/install_addons.sh image_creation_erplibre_package_timesheet payroll_code_on_task_type,payroll_period,payroll_preparation,payroll_preparation_export_wizard,payroll_preparation_from_timesheet,project_timesheet_time_control_enhanced,timesheet_edit_only_today,timesheet_list_description_after_task,timesheet_list_employee,timesheet_multi_line_wizard,timesheet_multi_line_wizard_security,timesheet_payroll_period,timesheet_validation_status
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_timesheet --restore_image erplibre_package_timesheet

.PHONY: image_db_create_erplibre_package_website
image_db_create_erplibre_package_website:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_website
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_website
	./script/addons/install_addons.sh image_creation_erplibre_package_website portal,website,website_blog,website_crm,website_crm_partner_assign,website_crm_phone_validation,website_customer,website_event,website_event_questions,website_event_sale,website_event_track,website_form,website_form_project,website_forum,website_google_map,website_hr,website_hr_recruitment,website_links,website_livechat,website_mail,website_mail_channel,website_mass_mailing,website_membership,website_partner,website_payment,website_rating,website_slides,website_survey,website_theme_install,website_twitter,website_adv_image_optimization,website_anchor_smooth_scroll,website_blog_excerpt_img,website_breadcrumb,website_canonical_url,website_cookie_notice,website_crm_privacy_policy,website_crm_quick_answer,website_crm_recaptcha,website_form_builder,website_form_recaptcha,website_google_tag_manager,website_img_dimension,website_js_below_the_fold,website_lazy_load_image,website_legal_page,website_logo,website_media_size,website_megamenu,website_odoo_debranding,website_portal_address,website_portal_contact,website_snippet_anchor,website_snippet_big_button,website_snippet_country_dropdown,website_snippet_marginless_gallery,smile_website_login_as,website_snippet_all
	./script/addons/install_addons_theme.sh image_creation_erplibre_package_website theme_default
#	./script/addons/install_addons.sh image_creation_erplibre_package_website website_no_crawler
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_website --restore_image erplibre_package_website

.PHONY: image_db_create_erplibre_package_wiki
image_db_create_erplibre_package_wiki:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_wiki
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_wiki
	./script/addons/install_addons.sh image_creation_erplibre_package_wiki document_page,document_page_approval,document_page_group,document_page_project,document_page_reference,document_page_tag,document_url,knowledge,attachment_preview,document_page_procedure,document_page_quality_manual,document_page_work_instruction,mgmtsystem,mgmtsystem_action,mgmtsystem_audit,mgmtsystem_hazard,mgmtsystem_manual,mgmtsystem_nonconformity,mgmtsystem_nonconformity_hr,mgmtsystem_nonconformity_product,mgmtsystem_nonconformity_project,mgmtsystem_quality,mgmtsystem_review,mgmtsystem_survey
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_wiki --restore_image erplibre_package_wiki

.PHONY: image_db_create_erplibre_package_dms
image_db_create_erplibre_package_dms:
	./.venv/bin/python3 ./odoo/odoo-bin db --drop --database image_creation_erplibre_package_dms
	./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database image_creation_erplibre_base --database image_creation_erplibre_package_dms
	./script/addons/install_addons.sh image_creation_erplibre_package_dms muk_dms,muk_dms_access,muk_dms_view,muk_web_preview,muk_web_preview_audio,muk_web_preview_csv,muk_web_preview_image,muk_web_preview_markdown,muk_web_preview_msoffice,muk_web_preview_opendocument,muk_web_preview_rst,muk_web_preview_text,muk_web_preview_video
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database image_creation_erplibre_package_dms --restore_image erplibre_package_dms

.PHONY: image_db_create_all
image_db_create_all:
	# TODO remove modules from addons/addons
	#./script/make.sh config_gen_image_db
	./script/database/db_restore.py --clean_cache
	./script/make.sh image_db_create_erplibre_base
	./script/make.sh image_db_create_erplibre_website
	./script/make.sh image_db_create_erplibre_code_generator
	./script/make.sh image_db_create_erplibre_demo
	./script/make.sh image_db_create_erplibre_package_accounting
	./script/make.sh image_db_create_erplibre_package_business_requirements
	./script/make.sh image_db_create_erplibre_package_contract
	./script/make.sh image_db_create_erplibre_package_crm
	./script/make.sh image_db_create_erplibre_package_e_commerce
	./script/make.sh image_db_create_erplibre_package_field_service
	./script/make.sh image_db_create_erplibre_package_helpdesk
	./script/make.sh image_db_create_erplibre_package_hr
	./script/make.sh image_db_create_erplibre_package_project
	./script/make.sh image_db_create_erplibre_package_purchase
	./script/make.sh image_db_create_erplibre_package_sale
	./script/make.sh image_db_create_erplibre_package_scrummer
	./script/make.sh image_db_create_erplibre_package_stock
	./script/make.sh image_db_create_erplibre_package_timesheet
	./script/make.sh image_db_create_erplibre_package_website
	./script/make.sh image_db_create_erplibre_package_wiki
	./script/make.sh image_db_create_erplibre_package_dms
	./script/make.sh image_db_create_test_website_attachments
	#./script/make.sh config_gen_all

.PHONY: image_db_create_all_parallel
image_db_create_all_parallel:
	./script/database/db_restore.py --clean_cache
	./script/make.sh image_db_create_erplibre_base
	parallel < ./conf/image_db_create.txt

.PHONY: image_db_create_test_website_attachments
image_db_create_test_website_attachments:
	./script/database/db_restore.py --database code_generator_test_website_attachements --image test_website_attachments
	# Do your stuff
	./.venv/bin/python3 ./odoo/odoo-bin --limit-time-real 999999 --no-http -c config.conf --stop-after-init -d code_generator_test_website_attachements -u all
	./.venv/bin/python3 ./odoo/odoo-bin db --backup --database code_generator_test_website_attachements --restore_image test_website_attachments

.PHONY: image_diff_base_website
image_diff_base_website:
	#./script/manifest/compare_backup.py --backup_file_1 ./image_db/erplibre_base.zip --backup_file_2 ./image_db/erplibre_website.zip
	./script/manifest/compare_backup.py --backup_1 erplibre_base --backup_2 erplibre_website

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
.PHONY: docker_build
docker_build:
	./script/docker/docker_build.sh

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

# generate config all repo
.PHONY: config_gen_all
config_gen_all:
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
