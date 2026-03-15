# Déploiement

- **Docker** : `docker-compose.yml` (PostgreSQL 18 + PostGIS 3.6)
- **Systemd** : `script/systemd/` pour les services
- **Nginx** : `script/nginx/` pour le reverse proxy
- **SSL** : Certbot pour les certificats
- **DNS** : `script/deployment/update_dns_cloudflare.py`

Plateformes supportées : Ubuntu 20.04-25.04, Linux Mint 22.3, Debian 12, Arch Linux, macOS (pyenv), Windows (WSL/Docker).
