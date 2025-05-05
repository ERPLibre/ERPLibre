############
# DATABASE #
############

.PHONY: db_list
db_list:
	./odoo_bin.sh db --list

.PHONY: db_list_incompatible_database
db_list_incompatible_database:
	./odoo_bin.sh db --list_incompatible_db

.PHONY: db_version
db_version:
	./odoo_bin.sh db --version

.PHONY: db_drop_db_test
db_drop_db_test:
	./odoo_bin.sh db --drop --database test

.PHONY: db_drop_db_test2
db_drop_db_test2:
	./odoo_bin.sh db --drop --database test2

.PHONY: db_drop_db_test3
db_drop_db_test3:
	./odoo_bin.sh db --drop --database test3

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

.PHONY: db_erplibre_base_db_test_update_all
db_erplibre_base_db_test_update_all:
	./script/addons/update_addons_all.sh test

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
