<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Social networks

Feeds and posting built into the TODO CLI, beside the mail client and on the
same principles: a local cache that answers offline, a secret that lives in
the vault and never in a file, and nothing that leaves the machine except
what you ask to send.

Every `Social > ...` path below is shorthand for
`TODO > [3] Assistant > [3] Social networks > ...`.

<!-- [fr] -->
# Réseaux sociaux

Les fils et la publication intégrés au CLI TODO, à côté du client courriel et
sur les mêmes principes : un cache local qui répond hors ligne, un secret qui
vit dans le coffre et jamais dans un fichier, et rien qui quitte la machine
sinon ce qu'on demande à envoyer.

Chaque chemin `Social > ...` ci-dessous est un raccourci pour
`TODO > [3] Assistant > [3] Réseaux sociaux > ...`.

<!-- [en] -->

## What it is
`TODO > Assistant > Social networks` reads the feeds of an account and
publishes to it, from the terminal, next to the mail client and on the same
principles: a local cache that answers offline, a secret that lives in the
vault and never in a file, and nothing that leaves the machine except what
you ask to send.

It is a SEPARATE screen from the mail client, not a tab inside it. A feed has
no folders, no growing UIDs and no drafts, and the gestures that matter are
not the same ones.

## The three platforms, and what each really allows

|  | Read the feed | Publish |
|---|---|---|
| Mastodon | yes | yes |
| Bluesky | yes | yes |
| LinkedIn | **no** | yes |

**A LinkedIn feed stays empty, by construction.** Retrieving a member's feed
needs an authorisation granted to a few chosen developers, and the activity
feed API is deprecated; only publishing is self-serve. The tree says so under
such an account instead of showing an empty node, which would read like a
fetch that never happened.

All three are implemented. LinkedIn publishes and does not read: its
transport refuses a feed WITHOUT calling, since the limit is known in advance
and calling would make it look like a breakdown of the day.

The two implemented ones authenticate differently, and it shows. Mastodon
takes a token you paste, valid until you revoke it. Bluesky opens a SESSION
from an app password and returns two tokens: a short access one and a durable
refresh one. The access token expires mid-session, the service names that
error, and the client refreshes instead of asking for the password again —
asking would be the mistake that error name exists to prevent.

## Adding an account

No client identifier ships with the repository: it would be public from the
first clone. Each platform offers a path where you obtain your own token.

| Platform | Where the token comes from |
|---|---|
| Mastodon | Preferences > Development > New application, scopes `read` and `write` |
| Bluesky | an app password created in the settings — never the account password |
| LinkedIn | an application in the developer portal carrying BOTH products: *Share on LinkedIn* (`w_member_social`, to publish) and *Sign In with LinkedIn using OpenID Connect* (`openid`, `profile`, to learn the member URN publishing requires). Both are self-serve; one alone gives a client that never publishes. |

The token goes into the vault, exactly like a mail password, and
`~/.erplibre/social/accounts.json` keeps only a reference to it. The file is
readable and repairable without being a place where a leak would hurt.

## The screen

| Key | Action |
|---|---|
| `r` / `R` | fetch the current account / every account |
| `c` | write a post |
| `a` | reply to the post under the cursor |
| `s` / `u` | mark the post read / unread |
| `M` | mark the whole feed read |
| `q` | quit |

## Fetching, and why a pass stops

A pass resumes from an opaque cursor the cache keeps, and paging descends
towards the past. It stops when the instance announces no more, or after five
pages — without that ceiling, a first pass on an old account would drag years
of feed back for a screen that shows only the top.

While the ceiling keeps interrupting the descent, the cursor makes the next
pass resume where it stopped, and new posts at the top wait for the descent
to finish. Once the instance stops announcing a next page, the cursor is
cleared and the following pass starts from the top again.

## Publishing twice is what the client refuses

The failure that matters when sending is not a refusal, it is silence: the
instance posts the message and the answer never arrives, leaving you unable
to tell which world you are in.

Every publication therefore carries an idempotency key, and the compose
screen keeps its own key as long as it is open. A send that fails leaves the
screen open with its text, so pressing send again replays the same key — and
the instance returns the post already created instead of creating a second
one. That is what makes the button safe to press twice.

On Bluesky there is no key to send: publishing means WRITING A RECORD at an
address the client chooses, and rewriting the same address replaces instead
of adding. That address has a shape the service enforces — thirteen
characters of a sorted alphabet, so that a repository stays ordered by
address — and replying there names TWO posts, the one answered and the
thread's root, each by address AND content fingerprint. An identifier alone
does not name a post, so the client carries the fingerprint in its cache. The guarantee is the same, the mechanism is not — the client keeps
the address exactly as it keeps a key, and a fresh one each try would publish
twice. That protocol carries no visibility either: the field is accepted so
the caller need not tell the networks apart, and ignored, since pretending to
honour it would suggest a privacy that does not exist.

LinkedIn offers NEITHER: no key to send, no address to rewrite. It refuses a
byte-identical repeat for about ten minutes with a 422 naming the post that
already exists — an anti-spam guard that expires, not a replay guarantee, and
changing one character defeats it. So when the answer is lost the client does
not retry
— it says it does not know, and asks you to check before sending again. That
is a third answer beside a refusal you correct and a breakdown you retry, and
the compose screen words it differently for that reason.

Send the same text again and that guard answers, which is the point: its
refusal is the ONLY signal that settles the doubt, since it proves the first
send went through. The client reads it, takes the post's address out of it
and shows you where to look, worded as a certainty rather than as one more
refusal. A refusal that names no post stays a duplicate and says so, without
pretending to know where to look.

The scopes the compose screen offers are those of the network you are
writing on: four on Mastodon, two on LinkedIn, one on Bluesky. The same list
everywhere let you pick a scope the network refuses, and the refusal only
came back after the round trip.

A refusal is told apart from a breakdown: a service saying no to an empty or
over-long post will not change its mind, while a broken gateway will. The
length allowed is asked of a Mastodon instance, which raises or lowers it; on
Bluesky it is the protocol's own 300 and on LinkedIn 3000, with nothing to
ask in either case.

## The cache

One SQLite per account under `~/.erplibre/social/<account>/`, in 0700 with
the database in 0600, sealable exactly like the mail cache. What is sealed:
the author, the display name, the text, the URI and the attachment
descriptions — that is who you read and what you read. What stays clear: the
date, because sorting ten thousand posts must not decrypt a row apiece.

A post's identifier is a STRING the platform chooses — a snowflake counter on
one, an `at://` URI on another — so the key is the pair feed plus identifier,
never a number this cache invented.

## Trying it against the real services

Nothing here has ever spoken to a real account. Every passing test runs
against sandbox servers written beside the client, by the same hand, and a
sandbox agrees with its author: two audits found four defects they could not
see — a header whose case was not the expected one, a record address the
service rejects, a reply naming only half of what it must, a success read as
a doubt. The walk below is therefore not a formality. It is the only thing
that tests the agreement with the service rather than with the sandbox.

Use a throwaway account, and delete the posts afterwards. Nothing from the
trial — handle, instance, token, post — belongs in this repository.

**Before anything.** One account per platform, each token in the vault as
the table above describes. `TODO > Assistant > Social networks > Fetch now`
reports every account without opening a screen: an account that answers
there holds a token the service accepts, which is the one thing worth
settling first.

**Mastodon.** Fetch, then fetch again: the pass must descend PAST the first
page. A feed that stops at exactly one page-worth of posts is the defect
where a service names its next page in a header whose case no one expected.
Then post under each of the four scopes, and check the service shows the
scope chosen. Then reply to a post from the feed, and check it appears under
it rather than as a new thread.

**Bluesky.** Fetch twice, as above; here the cursor travels in the body of
the answer. Then post twice in quick succession: TWO posts must appear. One
post where you made two means the second record overwrote the first, the
addresses having collided. Then reply, and check it lands under the right
post AND in the right thread — a reply names both, each by address and
content fingerprint.

**LinkedIn.** There is no feed and the screen says so; that is not a
breakdown. Post, and check it appears on the profile: a success returns no
body at all here, and a client that demands one reports a doubt over a post
that did go out. Then send the SAME text again, straight away: the service
refuses it and names the post already online, and the client must say it is
already online and where, not merely that it was refused.

Write down, for each step, what the client said and what the service shows.
A disagreement between those two is a defect, and it belongs in `tasks/`,
with the account and the instance generalised away. If the two agree on all
nine steps, this client has been tested against something it did not write.

<!-- [fr] -->

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
