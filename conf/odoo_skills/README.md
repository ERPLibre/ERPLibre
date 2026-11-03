# Skills d'agent d'Odoo

`.claude/skills/odoo-guidelines`, `odoo-web-guidelines`, `odoo-review`,
`odoo-security` et `odoo-git` sont la copie du répertoire `skills/` du dépôt
[odoo/odoo](https://github.com/odoo/odoo/tree/20.0/skills). Ils restent la
propriété d'Odoo S.A., sous la licence du dépôt d'origine (LGPL-3.0, voir son
`LICENSE` et son `COPYRIGHT`) ; `README.upstream.md` est leur mode d'emploi
d'origine.

| Fichier | Rôle |
| --- | --- |
| `UPSTREAM` | dépôt, branche suivie, commit et date de la copie installée |
| `erplibre.patch` | les seules retouches aux fichiers d'Odoo |
| `README.upstream.md` | le `skills/README.md` d'Odoo, au même commit |

## Ce qui appartient à qui

Les skills d'Odoo sont écrites pour la branche master (20.0). ERPLibre tourne
en 18.0 par défaut, où une partie de leurs API n'existe pas (`ir.access`,
`models.Constraint`, `fields.Domain`, routes `json2`...). Les écarts ne
s'écrivent pas dans les fichiers d'Odoo : chaque répertoire de skill porte un
`ERPLIBRE.md`, propre à ERPLibre, que la synchronisation ne touche jamais.

`erplibre.patch` se borne à ajouter en tête de chaque `SKILL.md` le renvoi
vers `ERPLIBRE.md`, et à restreindre les descriptions qui se déclencheraient
hors de leur domaine (`odoo-git` sur les commits d'ERPLibre, `odoo-review` et
`odoo-security` hors des addons, `odoo-web-guidelines` sur l'application
mobile). Plus il est court, moins une mise à niveau a de chances d'entrer en
conflit.

## Mettre à niveau

```bash
script/claude/sync_odoo_skills.sh --check     # le diff amont, rien n'est écrit
script/claude/sync_odoo_skills.sh             # installe la tête de la branche suivie
script/claude/sync_odoo_skills.sh --ref master
```

Le script rapatrie `skills/` seul par un clone partiel (quelques Mo), monte
la nouvelle copie à part, y applique `erplibre.patch`, et ne remplace la copie
installée qu'en cas de succès. Si le patch ne s'applique plus, rien n'est
modifié : reporter les retouches à la main dans `.claude/skills/odoo-*`, puis
`--save-patch` régénère le patch contre le commit noté.

Après une mise à niveau, relire le diff amont contre chaque `ERPLIBRE.md` :
une règle nouvelle ou changée vise master et peut ne pas valoir en 18. Une
skill apparue en amont est signalée, jamais installée d'office.
