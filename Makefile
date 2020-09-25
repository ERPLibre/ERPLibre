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
