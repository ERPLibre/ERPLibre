<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Deployment from Odoo

## Database backups larger than 1 GiB

The templates, Odoo 12 to 18, give `/web/database/backup` its own location.
With nginx's default `proxy_max_temp_file_size` of 1024m, a larger backup
arrives cut short: nginx stops reading Odoo past that size, the Odoo worker
gives up after its 2 s socket timeout, and the zip stops at about 1 GiB. That
location spools the whole backup to nginx's temporary directory
(`/var/lib/nginx/proxy` on Debian and Ubuntu), which therefore needs as much
free disk as the largest backup; raise `20480m` past that size. nginx takes
`k` or `m` for this directive, not `g`.

## Support Wildcard

You can support Wildcard domain, like *.mysite.com

Generate manually the certificate :

<!-- [fr] -->
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

<!-- [common] -->
```bash
sudo certbot certonly --manual --preferred-challenges=dns --server https://acme-v02.api.letsencrypt.org/directory -d "*.mysite.com" -d "*.mysecondsite.com"
```

<!-- [en] -->
Follow instruction. Manually update it each 90 days.

## Single domain per website

This solution will create nginx file and run certbot.

Because Odoo hasn't root password, you can exempt with command

<!-- [fr] -->
Suivez les instructions. Mettez-le à jour manuellement tous les 90 jours.

## Un seul domaine par site web

Cette solution va créer un fichier nginx et exécuter certbot.

Comme Odoo n'a pas de mot de passe root, vous pouvez l'exempter avec la commande

<!-- [common] -->
```bash
visudo
```

<!-- [en] -->
Add this content

<!-- [fr] -->
Ajoutez ce contenu

<!-- [common] -->
```text
odoo ALL=(root) NOPASSWD: /usr/sbin/nginx -t
odoo ALL=(root) NOPASSWD: /usr/bin/systemctl reload nginx
odoo ALL=(root) NOPASSWD: /bin/ln -s * /etc/nginx/sites-enabled/*
odoo ALL=(root) NOPASSWD: /home/odoo/erplibre/script/nginx/deploy_nginx_and_certbot.py
```

<!-- [en] -->
Run script

<!-- [fr] -->
Exécutez le script

<!-- [common] -->
```bash
sudo ./script/nginx/deploy_nginx_and_certbot.py --generate_nginx --run_certbot --domain DOMAINS;DOMAINS
```
