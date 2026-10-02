
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
| LinkedIn | une application du portail développeur portant les DEUX produits : *Share on LinkedIn* (`w_member_social`, pour publier) et *Sign In with LinkedIn using OpenID Connect* (`openid`, `profile`, pour connaître l'URN du membre qu'exige la publication). Les deux s'obtiennent en libre-service ; un seul donne un client qui ne publie jamais. |

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
remplace au lieu d'ajouter. Cette adresse a une forme que le service impose
— treize caractères d'un alphabet trié, pour qu'un dépôt reste rangé par
adresse — et y répondre nomme DEUX billets, celui auquel on répond et la
racine du fil, chacun par adresse ET empreinte de contenu. Un identifiant
seul ne désigne pas un billet, d'où l'empreinte gardée au cache. La garantie est la même, le mécanisme non — le
client garde l'adresse exactement comme il garde une clé, et en tirer une
neuve à chaque essai publierait deux fois. Ce protocole ne porte pas non plus
de visibilité : le champ est accepté pour que l'appelant n'ait pas à
distinguer les réseaux, et ignoré, prétendre l'honorer laissant croire à une
confidentialité qui n'existe pas.

LinkedIn n'offre NI L'UN NI L'AUTRE : aucune clé à envoyer, aucune adresse à
réécrire. Il refuse une répétition identique à l'octet pendant une dizaine de
minutes, par un 422 qui nomme le billet déjà là — un garde-fou anti-spam qui
expire, non une garantie de rejeu, et qu'un caractère changé suffit à
contourner. Aussi, quand la réponse se perd, le
client ne réessaie pas — il dit qu'il ne sait pas, et demande d'aller
vérifier avant de renvoyer. C'est une troisième réponse, à côté du refus
qu'on corrige et de la panne qu'on réessaie, et l'écran d'écriture la formule
autrement pour cette raison.

Renvoyer le même texte fait répondre ce garde-fou, et c'est tout l'intérêt :
son refus est le SEUL signal qui lève le doute, puisqu'il prouve que le
premier envoi a abouti. Le client le lit, en tire l'adresse du billet et
montre où regarder, formulé comme une certitude et non comme un refus de
plus. Un refus qui ne nomme aucun billet reste un doublon et le dit, sans
prétendre savoir où regarder.

Les portées que l'écran d'écriture propose sont celles du réseau sur lequel
on écrit : quatre sur Mastodon, deux sur LinkedIn, une sur Bluesky. La même
liste partout laissait choisir une portée que le réseau refuse, et le refus
ne revenait qu'après l'aller-retour.

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

## L'essayer contre les vrais services

Rien ici n'a jamais parlé à un compte réel. Tous les tests qui passent le
font contre des serveurs bacs à sable écrits à côté du client, de la même
main, et un bac à sable donne raison à son auteur : deux audits y ont trouvé
quatre défauts qu'ils ne pouvaient pas voir — un en-tête dont la casse
n'était pas celle attendue, une adresse d'enregistrement que le service
refuse, une réponse qui ne nommait que la moitié de ce qu'elle doit, un
succès lu comme un doute. Le parcours ci-dessous n'est donc pas une
formalité. C'est la seule chose qui éprouve l'accord avec le service plutôt
qu'avec le bac.

Prendre un compte jetable, et effacer les billets ensuite. Rien de l'essai —
identifiant, instance, jeton, billet — n'a sa place dans ce dépôt.

**Avant tout.** Un compte par plateforme, chaque jeton au coffre comme le
tableau plus haut le décrit. `TODO > Assistant > Réseaux sociaux > Rapporter
maintenant` rend l'état de chaque compte sans ouvrir d'écran : un compte qui
répond là porte un jeton que le service accepte, et c'est la seule chose à
régler avant le reste.

**Mastodon.** Rapporter, puis rapporter encore : la passe doit descendre
AU-DELÀ de la première page. Un fil qui s'arrête exactement sur une page de
billets, c'est le défaut où un service nomme sa page suivante dans un en-tête
dont personne n'attendait la casse. Puis publier sous chacune des quatre
portées, et vérifier que le service montre celle choisie. Puis répondre à un
billet du fil, et vérifier qu'il paraît sous lui et non en nouveau fil.

**Bluesky.** Rapporter deux fois, comme ci-dessus ; ici le curseur voyage
dans le corps de la réponse. Puis publier deux fois coup sur coup : DEUX
billets doivent paraître. Un seul là où l'on en a fait deux signifie que le
second enregistrement a écrasé le premier, les adresses ayant collisionné.
Puis répondre, et vérifier que cela tombe sous le bon billet ET dans le bon
fil — une réponse nomme les deux, chacun par adresse et empreinte de contenu.

**LinkedIn.** Il n'y a pas de fil et l'écran le dit ; ce n'est pas une panne.
Publier, et vérifier que le billet paraît au profil : un succès ne rend ici
aucun corps, et un client qui en exige un annonce un doute sur un billet
pourtant parti. Puis renvoyer LE MÊME texte, tout de suite : le service le
refuse en nommant le billet déjà en ligne, et le client doit dire qu'il est
déjà en ligne et où, non pas seulement qu'il a été refusé.

Noter, à chaque étape, ce que le client a dit et ce que le service montre. Un
désaccord entre les deux est un défaut, et il va dans `tasks/`, le compte et
l'instance généralisés. Si les deux s'accordent sur les neuf étapes, ce
client aura été éprouvé contre quelque chose qu'il n'a pas écrit lui-même.