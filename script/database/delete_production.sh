#!/usr/bin/env bash

. ./env_var.sh

echo -e "\n==== Delete user  ===="

echo -n "Are You Sure to delete user ${EL_HOME}? [Y/n]"
old_stty_cfg=$(stty -g)
stty raw -echo
answer=$( while ! head -c 1 | grep -i '[ny]' ;do true ;done )
stty $old_stty_cfg
if echo "$answer" | grep -iq "^y" ;then
    echo "Remove all system of ${EL_HOME}"
else
    echo "Cancel..."
    exit 1
fi

sudo systemctl stop ${EL_CONFIG}.service
# Disable daemon
sudo systemctl disable ${EL_CONFIG}.service
sudo rm -f /etc/systemd/system/${EL_CONFIG}.service

# Disable nginx
sudo rm -rf ${EL_HOME}
sudo rm -f /etc/nginx/sites-available/${EL_WEBSITE_NAME}
sudo rm -f /etc/nginx/sites-enabled/${EL_WEBSITE_NAME}
sudo systemctl restart nginx
