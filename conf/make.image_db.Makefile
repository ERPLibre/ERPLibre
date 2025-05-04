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
