#!/usr/bin/env python
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse

from os import listdir
from os.path import isdir, join, abspath

import configparser

parser = argparse.ArgumentParser(prog='Configure base dir for all addons')

parser.add_argument("addonsBaseDir", help="Path where addons are cloned.")
parser.add_argument("srcConfigPath",
                    help="Path where we retrieve source config file to adapt with new "
                         "addons path.")
parser.add_argument("dstConfigPath", help="Path to save adapted configuration.")

args = parser.parse_args()
addonsBaseDir = args.addonsBaseDir
srcConfigPath = args.srcConfigPath
dstConfigPath = args.dstConfigPath

addonsDirs = [abspath(join(addonsBaseDir, f)) for f in listdir(addonsBaseDir) if
              isdir(join(addonsBaseDir, f))]

# addonsDirs.insert(0, "/usr/lib/python3/dist-packages/odoo/addons/")
addonsDirs.insert(0, "/ERPLibre/addons/addons")
addonsDirs.insert(0, "/ERPLibre/odoo/addons/")

config = configparser.ConfigParser()

config.read(srcConfigPath)

separator = ","

config.set('options', 'addons_path', separator.join(addonsDirs))

print(config.get('options', 'addons_path'))

with open(dstConfigPath, 'w') as configfile:
    config.write(configfile)
