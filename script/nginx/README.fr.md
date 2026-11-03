
# Déploiement depuis Odoo

## Sauvegardes de base de plus de 1 Gio

Les templates, d'Odoo 12 à 18, donnent à `/web/database/backup` son propre
bloc `location`. Avec le `proxy_max_temp_file_size` par défaut de nginx,
1024m, une sauvegarde plus grosse arrive coupée : au-delà de cette taille,
nginx cesse de lire Odoo, le worker d'Odoo abandonne après le délai de 2 s de
sa socket, et le zip s'arrête vers 1 Gio. Ce bloc garde la sauvegarde entière
dans le répertoire temporaire de nginx (`/var/lib/nginx/proxy` sur Debian et
Ubuntu), qui doit donc avoir autant d'espace libre que la plus grosse
sauvegarde ; montez `20480m` au-delà de cette taille. nginx accepte `k` ou `m`
pour cette directive, pas `g`.

## Support Wildcard

Vous pouvez supporter les domaines Wildcard, comme *.mysite.com

Générez manuellement le certificat :

```bash
sudo certbot certonly --manual --preferred-challenges=dns --server https://acme-v02.api.letsencrypt.org/directory -d "*.mysite.com" -d "*.mysecondsite.com"
```

Suivez les instructions. Mettez-le à jour manuellement tous les 90 jours.

## Un seul domaine par site web

Cette solution va créer un fichier nginx et exécuter certbot.

Comme Odoo n'a pas de mot de passe root, vous pouvez l'exempter avec la commande

```bash
visudo
```

Ajoutez ce contenu

```text
odoo ALL=(root) NOPASSWD: /usr/sbin/nginx -t
odoo ALL=(root) NOPASSWD: /usr/bin/systemctl reload nginx
odoo ALL=(root) NOPASSWD: /bin/ln -s * /etc/nginx/sites-enabled/*
odoo ALL=(root) NOPASSWD: /home/odoo/erplibre/script/nginx/deploy_nginx_and_certbot.py
```

Exécutez le script

```bash
sudo ./script/nginx/deploy_nginx_and_certbot.py --generate_nginx --run_certbot --domain DOMAINS;DOMAINS
```