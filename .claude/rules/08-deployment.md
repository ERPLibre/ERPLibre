# Déploiement

- **Docker** : `docker-compose.yml` (PostgreSQL 18 + PostGIS 3.6)
- **Systemd** : `script/systemd/` pour les services
- **Nginx** : `script/nginx/` pour le reverse proxy
- **SSL** : Certbot pour les certificats
- **DNS** : `script/deployment/update_dns_cloudflare.py`

Plateformes supportées : Ubuntu 24.04 / 25.10 / 26.04, Linux Mint 22.3,
Debian 12, AlmaLinux 9+, Rocky Linux 9+, CentOS Stream 10, openSUSE
Tumbleweed, Arch Linux, macOS (pyenv),
Windows (WSL/Docker).

Ubuntu 20.04 et 22.04 sont abandonnées : pikepdf exige qpdf >= 12.2, compilé
en C++20, quand focal livre GCC 9.
