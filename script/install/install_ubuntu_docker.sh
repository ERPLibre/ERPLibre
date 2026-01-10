#!/usr/bin/env bash

# From https://docs.docker.com/engine/install/ubuntu/
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
# Certbot
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
