
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

```bash
# La ligne ssh d'une fiche, sans rien joindre :
python3 -c "from script.remote import appliance_ssh as A; \
  print(' '.join(A.ssh_argv({'target': 'root@203.0.113.5', \
  'jump': 'rebond', 'port': '22'}, 'uname -a')))"
```