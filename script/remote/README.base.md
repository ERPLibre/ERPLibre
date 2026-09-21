<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Reaching a remote machine

Four modules, one rule: **a single execution contract**. Anything that runs
a command elsewhere goes through it, and a second path composed alongside
would silently lose what it guarantees.

## `appliance_ssh` — the contract

One function runs, and it never raises:

- **privilege** — a non-empty `sudo` wraps the WHOLE chain, not its first
  word;
- **timeout** — returns `(255, "timeout")`, never an exception;
- **system error** — returns `255` and the reason, never a traceback;
- **ssh noise** — banners and warnings are stripped, so a parser reads the
  command's answer and not the transport's;
- **input stream** — a file lands over there on the remote command's
  standard input, through this same function.

The option order in the ssh line is **fixed** — port, key, jump — so that
the same record always renders the same line: it is what allows comparing
two versions of the function byte for byte.

## `host_probe` — saying what is in front, without naming a product

A closed vocabulary: `ok`, `hostkey`, `product-absent`, `unreachable`, `needs-root`, `no-privilege`. Telling them apart is the
whole point — "the tool is not there", "I could not look" and "the key is
not known here" send you to three different places.

`detail` is the line that TEACHES something: what the product's probe
answered, not what the liveness test said. "command not found" is the useful
proof; "ok" is not.

Privilege has three modes, because refusing a host that only needs `sudo`
for two verbs out of eleven would forbid the nine that work: `required`, `optional`, `skip`.

**The module names no product.** A test forbids it: hardcoding one would
make the probe lie the day the same answer comes from another.

## `deploy_target` — named targets

A target is what you write and read back; a **record** is what the transport
consumes. The two do not merge: a screen name has nothing to do in an ssh
line, and `fiche()` is the adapter.

Two kinds today: one RECEIVES a deployment, the other RECEIVES backups.
Merging them would deploy onto the archive store.

## `host_memory` — the appliance one has chosen

An appliance menu has dozens of entries and they all talk to the same
machine. The choice therefore lives at two levels — a process cache, and the
preferences, which make it survive the menu closing. This module **asks
nothing and prints nothing**: choosing a host is a conversation, and it
belongs to the menu.

<!-- [fr] -->
# Joindre une machine distante

Quatre modules, une règle : **un seul contrat d'exécution**. Tout ce qui
lance une commande ailleurs y passe, et un second chemin composé à côté
perdrait en silence ce qu'il garantit.

## `appliance_ssh` — le contrat

Une fonction exécute, et elle ne lève jamais :

- **le privilège** — un `sudo` non vide enveloppe TOUTE la suite, pas son
  premier mot ;
- **le délai** — rendu en `(255, "timeout")`, jamais en exception ;
- **l'erreur système** — rendue en `255` et sa raison, jamais en trace
  d'appel ;
- **le bruit ssh** — bannières et avertissements sont dépouillés, pour
  qu'un analyseur lise la réponse de la commande et non celle du transport ;
- **le flux d'entrée** — un fichier se dépose là-bas par l'entrée standard
  de la commande distante, par cette même fonction.

L'ordre des options de la ligne ssh est **fixe** — port, clé, rebond — pour
qu'une même fiche rende toujours la même ligne : c'est ce qui permet de
comparer deux versions de la fonction octet pour octet.

## `host_probe` — dire ce qu'il y a en face, sans nommer de produit

Vocabulaire clos : `ok`, `hostkey`, `product-absent`, `unreachable`, `needs-root`, `no-privilege`. Les distinguer est tout le
sujet — « l'outil n'est pas là », « je n'ai pas pu regarder » et « la clé
n'est pas connue ici » envoient à trois endroits différents.

`detail` est la ligne qui APPREND quelque chose : ce que la sonde du produit
a répondu, et non ce que le test de vie a dit. « command not found » est la
preuve utile, « ok » ne l'est pas.

Le privilège a trois modes, parce que refuser un hôte qui n'a besoin de
`sudo` que pour deux verbes sur onze interdirait les neuf qui marchent : `required`, `optional`, `skip`.

**Le module ne nomme aucun produit.** Une épreuve l'interdit : en coder un
en dur ferait mentir la sonde le jour où la même réponse vient d'un autre.

## `deploy_target` — les cibles nommées

Une cible est ce qu'on écrit et relit ; une **fiche** est ce qu'on donne au
transport. Les deux ne se confondent pas : un nom d'écran n'a rien à faire
dans une ligne ssh, et `fiche()` est l'adaptateur.

Deux genres aujourd'hui : l'une REÇOIT un déploiement, l'autre REÇOIT les
sauvegardes. Les confondre déploierait sur le dépôt d'archives.

## `host_memory` — l'appliance qu'on a choisie

Un menu d'appliance compte des dizaines d'entrées et elles parlent toutes à
la même machine. Le choix vit donc à deux étages — un cache de processus, et
les préférences, qui le font survivre à la fermeture du menu. Ce module **ne
demande rien et n'affiche rien** : choisir un hôte est une conversation, et
elle appartient au menu.

<!-- [common] -->
```bash
# La ligne ssh d'une fiche, sans rien joindre :
python3 -c "from script.remote import appliance_ssh as A; \
  print(' '.join(A.ssh_argv({'target': 'root@203.0.113.5', \
  'jump': 'rebond', 'port': '22'}, 'uname -a')))"
```
