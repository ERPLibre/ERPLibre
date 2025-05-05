#################
# DOCUMENTATION #
#################

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
	source ./.venv.erplibre/bin/activate && make -C doc/itpp-labs_odoo-development/docs html || exit 1

.PHONY: open_doc_dev
open_doc_dev:
	-$(BROWSER) doc/itpp-labs_odoo-development/docs/_build/html/index.html

.PHONY: doc_clean_dev
doc_clean_dev:
	make -C doc/itpp-labs_odoo-development/docs clean

# documentation migration
.PHONY: doc_migration
doc_migration:
	source ./.venv.erplibre/bin/activate && make -C doc/itpp-labs_odoo-port-docs/docs html || exit 1

.PHONY: open_doc_migration
open_doc_migration:
	-$(BROWSER) doc/itpp-labs_odoo-port-docs/docs/_build/html/index.html

.PHONY: doc_clean_migration
doc_clean_migration:
	make -C doc/itpp-labs_odoo-port-docs/docs clean

# documentation test
.PHONY: doc_test
doc_test:
	source ./.venv.erplibre/bin/activate && make -C doc/itpp-labs_odoo-test-docs/doc-src html || exit 1

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
	source ./.venv.erplibre/bin/activate && make -C doc/odoo_documentation-user html || exit 1

.PHONY: open_doc_user
open_doc_user:
	-$(BROWSER) doc/odoo_documentation-user/_build/html/index.html

.PHONY: doc_clean_user
doc_clean_user:
	make -C doc/odoo_documentation-user clean

# documentation markdown
.PHONY: doc_markdown
doc_markdown:
	./.venv.erplibre/bin/mmg --verbose --yes ./doc/CODE_GENERATOR.base.md
