
# Réseaux sociaux

Les fils et la publication intégrés au CLI TODO, à côté du client courriel et
sur les mêmes principes : un cache local qui répond hors ligne, un secret qui
vit dans le coffre et jamais dans un fichier, et rien qui quitte la machine
sinon ce qu'on demande à envoyer.

Chaque chemin `Social > ...` ci-dessous est un raccourci pour
`TODO > [3] Assistant > [3] Réseaux sociaux > ...`.


## Ce que c'est

`TODO > Assistant > Réseaux sociaux` lit les fils d'un compte et y publie,
depuis le terminal, à côté du client courriel et sur les mêmes principes : un
cache local qui répond hors ligne, un secret qui vit dans le coffre et jamais
dans un fichier, et rien qui quitte la machine sinon ce qu'on demande à
envoyer.

C'est un écran SÉPARÉ de celui du courriel, et non un onglet dedans. Un fil
n'a ni dossiers, ni UID croissants, ni brouillons, et les gestes qui comptent
n'y sont pas les mêmes.

## Les trois plateformes, et ce que chacune permet vraiment

|  | Lire le fil | Publier |
|---|---|---|
| Mastodon | oui | oui |
| Bluesky | oui | oui |
| LinkedIn | **non** | oui |

**Un fil LinkedIn reste vide, par construction.** Récupérer le fil d'un
membre exige une autorisation accordée à quelques développeurs choisis, et
l'API de fil d'activité est dépréciée ; seule la publication est en
libre-service. L'arbre le dit sous un tel compte au lieu d'afficher un nœud
vide, qui se lirait comme une synchronisation qui n'a pas eu lieu.

Seul Mastodon est implémenté pour l'instant. Bluesky et LinkedIn ont leurs
préréglages et leurs comptes, et pas encore de transport.

## Ajouter un compte

Aucun identifiant client n'est livré avec le dépôt : il serait public dès le
premier clone. Chaque plateforme offre un chemin où l'on obtient le sien.

| Plateforme | D'où vient le jeton |
|---|---|
| Mastodon | Préférences > Développement > Nouvelle application, portées `read` et `write` |
| Bluesky | un mot de passe d'application créé dans les réglages — jamais celui du compte |
| LinkedIn | une application qu'on enregistre, et que LinkedIn approuve |

Le jeton va au coffre, exactement comme un mot de passe courriel, et
`~/.erplibre/social/accounts.json` n'en garde qu'une référence. Le fichier
reste lisible et réparable sans devenir un endroit d'où une fuite ferait mal.

## L'écran

| Touche | Action |
|---|---|
| `r` / `R` | rapporter le compte courant / tous les comptes |
| `c` | écrire un billet |
| `a` | répondre au billet sous le curseur |
| `s` / `u` | marquer le billet lu / non lu |
| `M` | marquer tout le fil lu |
| `q` | quitter |

## Rapporter, et pourquoi une passe s'arrête

Une passe reprend à un curseur opaque gardé par le cache, et la pagination
DESCEND vers le passé. Elle s'arrête quand l'instance n'annonce plus de
suite, ou au bout de cinq pages — sans ce plafond, une première passe sur un
compte ancien remonterait des années de fil pour un écran qui n'en montre que
le haut.

Tant que le plafond interrompt la descente, le curseur fait reprendre la
passe suivante où elle s'était arrêtée, et les billets neufs du haut
attendent qu'elle soit finie. L'instance cessant d'annoncer une suite, le
curseur est effacé et la passe d'après repart du haut.

## Publier deux fois est ce que le client refuse

La panne qui compte à l'envoi n'est pas le refus mais le silence : l'instance
pose le billet et la réponse n'arrive jamais, sans qu'on puisse dire lequel
des deux mondes on habite.

Chaque publication porte donc une clé d'idempotence, et l'écran d'écriture
garde la sienne tant qu'il est ouvert. Un envoi qui échoue laisse l'écran
ouvert avec son texte : presser à nouveau rejoue la même clé — et l'instance
rend le billet déjà créé au lieu d'en poser un second. C'est ce qui rend le
bouton sûr à presser deux fois.

Un refus se distingue d'une panne : une instance qui dit non à un billet vide
ou trop long ne changera pas d'avis, une passerelle en vrac si. La longueur
permise se demande à l'instance, qui la relève ou l'abaisse, et une question
sans réponse retombe sur 500 plutôt que d'empêcher l'envoi.

## Le cache

Un SQLite par compte sous `~/.erplibre/social/<compte>/`, en 0700 avec la
base en 0600, scellable exactement comme le cache courriel. Ce qui est
scellé : l'auteur, le nom affiché, le texte, l'URI et les descriptions des
pièces — c'est qui on lit et ce qu'on lit. Ce qui reste en clair : la date,
parce que trier dix mille billets ne doit pas déchiffrer une ligne chacun.

L'identifiant d'un billet est une CHAÎNE que la plateforme choisit — un
compteur à flocon sur l'une, une URI `at://` sur l'autre — donc la clé est la
paire fil plus identifiant, jamais un nombre inventé par ce cache.