#!/usr/bin/env bash

# https://docs.docker.com/engine/install/debian/
# Docker
curl -fsSL https://get.docker.com | sh

# nginx
sudo apt-get install -y nginx

# Snap installation
# https://snapcraft.io/docs/installing-snap-on-debian
sudo apt install -y snapd
sudo snap install core
sudo snap refresh core

# https://certbot.eff.org/lets-encrypt/debianbuster-nginx
# Cerbot
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
