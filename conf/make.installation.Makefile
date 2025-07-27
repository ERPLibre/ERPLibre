###########
# INSTALL #
###########

.PHONY: install
install:install_os install_dev

.PHONY: install_dev
install_dev:
	#	./script/version/update_env_version.py
	#	./script/install/install_locally_dev.sh
	./script/version/update_env_version.py --install_dev

.PHONY: install_odoo_18
install_odoo_18:
	./script/version/update_env_version.py --erplibre_version odoo18.0_python3.12.10 --install_dev

.PHONY: switch_odoo_18
switch_odoo_18:
	./script/version/update_env_version.py --erplibre_version odoo18.0_python3.12.10 --switch
	./script/make.sh config_gen_all

.PHONY: install_odoo_17
install_odoo_17:
	./script/version/update_env_version.py --erplibre_version odoo17.0_python3.10.18 --install_dev

.PHONY: switch_odoo_17
switch_odoo_17:
	./script/version/update_env_version.py --erplibre_version odoo17.0_python3.10.18 --switch
	./script/make.sh config_gen_all

.PHONY: install_odoo_16
install_odoo_16:
	./script/version/update_env_version.py --erplibre_version odoo16.0_python3.10.18 --install_dev

.PHONY: switch_odoo_16
switch_odoo_16:
	./script/version/update_env_version.py --erplibre_version odoo16.0_python3.10.18 --switch
	./script/make.sh config_gen_all

.PHONY: install_odoo_15
install_odoo_15:
	./script/version/update_env_version.py --erplibre_version odoo15.0_python3.8.20 --install_dev

.PHONY: switch_odoo_15
switch_odoo_15:
	./script/version/update_env_version.py --erplibre_version odoo15.0_python3.8.20 --switch
	./script/make.sh config_gen_all

.PHONY: install_odoo_14
install_odoo_14:
	./script/version/update_env_version.py --erplibre_version odoo14.0_python3.8.20 --install_dev

.PHONY: switch_odoo_14
switch_odoo_14:
	./script/version/update_env_version.py --erplibre_version odoo14.0_python3.8.20 --switch
	./script/make.sh config_gen_all

.PHONY: install_odoo_13
install_odoo_13:
	./script/version/update_env_version.py --erplibre_version odoo13.0_python3.7.17 --install_dev

.PHONY: switch_odoo_13
switch_odoo_13:
	./script/version/update_env_version.py --erplibre_version odoo13.0_python3.7.17 --switch
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
	./script/make.sh install_odoo_18
	./script/make.sh install_odoo_17
	./script/make.sh install_odoo_16
	./script/make.sh install_odoo_15
	./script/make.sh install_odoo_14
	./script/make.sh install_odoo_13
	./script/make.sh install_odoo_12

.PHONY: install_odoo_all_version_dev
install_odoo_all_version_dev:
	echo "Open Pycharm, close it before install Odoo and reopen at the end"
	pycharm .
	./script/make.sh install_odoo_all_version

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
