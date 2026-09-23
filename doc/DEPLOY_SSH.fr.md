
# Déployer par SSH : la cible nommée

`TODO › Deploy › SSH (remote host)` agit sur une machine décrite une fois et
retrouvée ensuite. Auparavant, chacun de ses onze verbes posait cinq
questions — adresse, compte, port, clé, chemin — et n'en retenait aucune.

## Ce que porte une cible


| champ | |
|---|---|
| `name` | `[a-z0-9][a-z0-9_-]{0,30}` |
| `target` | `compte@hôte`, ou un alias de `~/.ssh/config` |
| `jump` | rebond, vide pour une connexion directe |
| `port` | vide : ssh décide, donc un alias garde le sien |
| `identity` | clé privée, vide : `~/.ssh/config` décide |
| `path` | où vit ERPLibre, défaut `~/erplibre_deploy_2` |
| `domain` | non vide ≡ servi en HTTPS derrière nginx |
| `admin_email` | pour le certificat |
| `verdict` `version` `sudo` `last_probe` | ce que la sonde a trouvé |

## Deux magasins, et pourquoi

L'**inventaire** — quelles machines existent — est une donnée de site. Il
vit sous `deploy_targets` dans les trois fichiers de configuration que
`ConfigFile` fusionne, et ne s'écrit que dans
`private/todo/todo_override_private.json` : le seul des trois qui soit
gitignored, écrit de façon atomique en `0600`.

La **sélection** — à quelle machine on parle en ce moment — est une
préférence d'écran et vit avec les autres préférences. Les séparer est
voulu : remettre ses préférences à zéro ne doit pas effacer un inventaire.

Seul le *nom* est retenu, et la fiche est relue à chaque lecture. Recopier
la fiche la ferait vieillir dès la première modification, et l'écran
nommerait une machine qui a changé d'adresse.

Une cible venue du fichier partagé peut être corrigée : l'entrée privée la
remplace sous le même nom, et supprimer la correction fait revenir la
partagée.

## Aucun drapeau `prod`

Le mot recouvre deux questions distinctes, et la cible répond aux deux sans
nommer ni l'une ni l'autre :

- *ce service est-il exposé ?* — c'est `domain`. Non vide, il est servi
  derrière nginx avec un certificat.
- *quelle posture a la machine ?* — c'est `path` : un checkout sous `/opt`
  et un checkout sous un répertoire personnel ne sont pas la même
  installation.

Un champ, une vérité. Un booléen lu à plusieurs endroits dériverait de celle
des deux questions à laquelle il ne répondait pas.

## Vérifier une cible

`SSH - Check connection` lit le fichier de version au chemin propre à la
cible. Le résultat se dit par couche, parce que « ssh passe, le produit
manque » et « rien ne répond » se corrigent de deux côtés opposés.
L'élévation est *constatée* et non exigée : deux verbes sur onze en ont
besoin, et refuser la machine pour eux fermerait les neuf autres. Ce qui est
trouvé s'écrit sur la fiche, avec sa date.