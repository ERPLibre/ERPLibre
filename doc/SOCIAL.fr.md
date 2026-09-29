
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

Les trois sont implémentés. LinkedIn publie et ne lit pas : son transport
refuse un fil SANS APPELER, la limite étant connue d'avance et l'appel la
ferait passer pour une panne du jour.

Les deux implémentés ne s'authentifient pas pareil, et cela se voit. Mastodon
prend un jeton qu'on colle, valable jusqu'à révocation. Bluesky ouvre une
SESSION à partir d'un mot de passe d'application et rend deux jetons : un
d'accès, court, et un de rafraîchissement, durable. L'accès expire en cours
de session, le service nomme cette erreur, et le client rafraîchit au lieu de
redemander le mot de passe — le redemander serait l'erreur que ce nom existe
pour éviter.

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

Sur Bluesky il n'y a pas de clé à envoyer : publier, c'est ÉCRIRE UN
ENREGISTREMENT à une adresse que le client choisit, et réécrire la même
remplace au lieu d'ajouter. La garantie est la même, le mécanisme non — le
client garde l'adresse exactement comme il garde une clé, et en tirer une
neuve à chaque essai publierait deux fois. Ce protocole ne porte pas non plus
de visibilité : le champ est accepté pour que l'appelant n'ait pas à
distinguer les réseaux, et ignoré, prétendre l'honorer laissant croire à une
confidentialité qui n'existe pas.

LinkedIn n'offre NI L'UN NI L'AUTRE : deux demandes identiques font deux
publications, et rien ne peut l'empêcher. Aussi, quand la réponse se perd, le
client ne réessaie pas — il dit qu'il ne sait pas, et demande d'aller
vérifier avant de renvoyer. C'est une troisième réponse, à côté du refus
qu'on corrige et de la panne qu'on réessaie, et l'écran d'écriture la formule
autrement pour cette raison.

Un refus se distingue d'une panne : un service qui dit non à un billet vide
ou trop long ne changera pas d'avis, une passerelle en vrac si. La longueur
permise se demande à une instance Mastodon, qui la relève ou l'abaisse ; sur
Bluesky c'est le 300 du protocole et sur LinkedIn 3000, sans rien à demander
dans les deux cas.

## Le cache

Un SQLite par compte sous `~/.erplibre/social/<compte>/`, en 0700 avec la
base en 0600, scellable exactement comme le cache courriel. Ce qui est
scellé : l'auteur, le nom affiché, le texte, l'URI et les descriptions des
pièces — c'est qui on lit et ce qu'on lit. Ce qui reste en clair : la date,
parce que trier dix mille billets ne doit pas déchiffrer une ligne chacun.

L'identifiant d'un billet est une CHAÎNE que la plateforme choisit — un
compteur à flocon sur l'une, une URI `at://` sur l'autre — donc la clé est la
paire fil plus identifiant, jamais un nombre inventé par ce cache.