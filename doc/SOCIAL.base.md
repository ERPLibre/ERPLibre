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

Only Mastodon is implemented so far. Bluesky and LinkedIn have their presets
and their accounts, and no transport yet.

## Adding an account

No client identifier ships with the repository: it would be public from the
first clone. Each platform offers a path where you obtain your own token.

| Platform | Where the token comes from |
|---|---|
| Mastodon | Preferences > Development > New application, scopes `read` and `write` |
| Bluesky | an app password created in the settings — never the account password |
| LinkedIn | an application you register, which LinkedIn approves |

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

A refusal is told apart from a breakdown: an instance saying no to an empty
or over-long post will not change its mind, while a broken gateway will. The
length allowed is asked of the instance, which raises or lowers it, and an
unanswered question falls back on 500 rather than blocking the send.

## The cache

One SQLite per account under `~/.erplibre/social/<account>/`, in 0700 with
the database in 0600, sealable exactly like the mail cache. What is sealed:
the author, the display name, the text, the URI and the attachment
descriptions — that is who you read and what you read. What stays clear: the
date, because sorting ten thousand posts must not decrypt a row apiece.

A post's identifier is a STRING the platform chooses — a snowflake counter on
one, an `at://` URI on another — so the key is the pair feed plus identifier,
never a number this cache invented.

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
