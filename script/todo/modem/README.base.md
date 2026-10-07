<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Cellular gateway — what to restart, and what is lost

Two long-running services share one modem. Neither reloads its code or its
secrets on its own, and each loses something different when it stops. This
page says what, because the failures it causes look like something else:
a fetch that never happens, a message that stays on disk, a cut that keeps
the old boundaries.

## The two services

`erplibre-sip-go` holds the AT port and the modem's sound card for as long
as it runs. It answers incoming calls, records on the answering machine,
watches the SIM's message-waiting flag and calls the operator's mailbox.

`erplibre-passerelle-modem` talks to Odoo: it relays SMS, reports incoming
calls, and picks up what the voice service drops — cutting the message out
of a fetch and uploading it.

## What to restart after a change

| Changed | Restart | What it costs |
|---|---|---|
| `script/erplibre_sip_go/*.go`, after rebuilding | `erplibre-sip-go` | the voicemail PIN is lost |
| `script/todo/modem/*.py` | `erplibre-passerelle-modem` | nothing |
| an Odoo model or view | update the module, then reload the tab | nothing |

Python loads a module once. An agent started before an edit keeps the old
code in memory and will go on cutting with the old boundaries, with nothing
in its log to say so.

## What is lost on a restart

The voicemail PIN lives in a vault only a person can open, so the service is
HANDED it and keeps it in memory alone. It is written to no disk, no
database and no repository — and it disappears when the service stops. Hand
it over again from **TODO › Modem › Answering machine**; the fetch refuses
and says so when it is missing.

## One port, one holder

The AT port is taken with an exclusive lock. A recipe played from the menu
therefore cannot run while the voice service does: stop it, fetch, start it
again. A fetch commanded from Odoo has no such problem — the service holds
the port and plays the recipe itself.

## Gains held by the service

The service asserts the modem's two audio gains at every startup: downlink
tripled, so recordings are audible, and uplink left at unity, because a
browser already normalises what its microphone picks up and multiplying
again clips. Asserting them each time is deliberate: a gain set by hand
drifts, and a clipped call sounds broken without anything saying why.

<!-- [fr] -->
# Passerelle cellulaire — ce qu'il faut relancer, et ce qui se perd

Deux services au long cours se partagent un seul modem. Ni l'un ni l'autre
ne recharge son code ni ses secrets tout seul, et chacun perd quelque chose
de différent en s'arrêtant. Cette page dit quoi, parce que les pannes que
ça produit ressemblent à autre chose : un relèvement qui ne part pas, un
message qui reste sur disque, une découpe qui garde les anciennes bornes.

## Les deux services

`erplibre-sip-go` tient le port AT et la carte son du modem tant qu'il
tourne. Il présente les appels entrants, enregistre au répondeur, surveille
le drapeau de message de la SIM et appelle la boîte vocale de l'opérateur.

`erplibre-passerelle-modem` parle à Odoo : il relaie les SMS, rapporte les
appels entrants, et ramasse ce que le service de voix dépose — il découpe le
message d'un relèvement et le téléverse.

## Quoi relancer après un changement

| Changé | Relancer | Ce que ça coûte |
|---|---|---|
| `script/erplibre_sip_go/*.go`, après recompilation | `erplibre-sip-go` | le NIP de la messagerie est perdu |
| `script/todo/modem/*.py` | `erplibre-passerelle-modem` | rien |
| un modèle ou une vue Odoo | mettre à jour le module, puis rafraîchir l'onglet | rien |

Python charge un module une fois. Un agent démarré avant une modification
garde l'ancien code en mémoire et continuera de découper avec les anciennes
bornes, sans que rien dans son journal ne le dise.

## Ce qui se perd à un redémarrage

Le NIP de la messagerie vit dans un coffre qu'une personne seule peut
ouvrir : on le REMET au service, qui le garde en mémoire et nulle part
ailleurs. Il n'est écrit ni sur le disque, ni en base, ni dans le dépôt — et
il disparaît à l'arrêt du service. Il se remet par **TODO › Modem ›
Répondeur** ; le relèvement refuse et le dit quand il manque.

## Un port, un détenteur

Le port AT se prend avec un verrou exclusif. Une recette jouée depuis le
menu ne peut donc pas tourner pendant que le service de voix tourne :
l'arrêter, relever, le relancer. Un relèvement commandé depuis Odoo n'a pas
ce problème — le service tient le port et joue la recette lui-même.

## Les gains que le service tient

Le service réaffirme les deux gains audio du modem à chaque démarrage : la
descente triplée, pour que les enregistrements s'entendent, et la montée
laissée à l'unité, parce qu'un navigateur normalise déjà ce que son micro
capte et que multiplier par-dessus écrête. Les réaffirmer chaque fois est
voulu : un gain posé à la main dérive, et un appel écrêté sonne cassé sans
que rien n'en dise la raison.
