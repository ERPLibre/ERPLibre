#!/bin/bash
################################################################################
# Script for installing Odoo on Ubuntu 14.04, 15.04, 16.04 and 18.04 (could be used for other version too)
# Author: Yenthe Van Ginneken
#-------------------------------------------------------------------------------
# This script will install Odoo on your Ubuntu 16.04 server. It can install multiple Odoo instances
# in one Ubuntu because of the different xmlrpc_ports
#-------------------------------------------------------------------------------
################################################################################

OE_USER="odoo"
OE_HOME="/${OE_USER}"
OE_HOME_ODOO="${OE_HOME}/odoo"
OE_HOME_EXT="${OE_HOME_ODOO}/odoo"
# The default port where this Odoo instance will run under (provided you use the command -c in the terminal)
# Set to true if you want to install it, false if you don't need it or have it already installed.
INSTALL_WKHTMLTOPDF="True"
# Set the default Odoo port (you still have to use -c /etc/odoo-server.conf for example to use this.)
OE_PORT="8069"
OE_LONGPOLLING_PORT="8072"
# set the superadmin password
OE_SUPERADMIN="admin"
OE_VERSION="stable_prod_12.0"
OE_CONFIG="${OE_USER}"
MINIMAL_ADDONS="False"
# Set this to True if you want to install Nginx!
INSTALL_NGINX="True"
# Set the website name
WEBSITE_NAME="_"
GITHUB_TOKEN=""
