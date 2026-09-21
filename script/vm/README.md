
# VM backends

Three backends, one vocabulary: **the identity chooses the backend**, and a
screen no longer has to know which one.

## The package depends on nothing

Not a menu, not a screen, not a terminal — **not even the postures**. A test
holds it at the level of the PACKAGE, so that the module written next
inherits the rule without anyone thinking about it. What it protects is not
an elegance: a backend importing a menu module would become untestable
without a terminal, and the first consumer of a second screen would copy it
rather than pull on that thread.

It is the CALLER that brings the two together. Egress rules reach an
instance as a composed script, never as a posture the package would read.

## The handle: what commands a machine, and proves it is the right one

| Field | What it is |
|---|---|
| `backend` | `libvirt`, `pve` or `lima` |
| `name` | What a human calls it |
| `key` | What ADDRESSES it — a name for libvirt, a VMID on a Proxmox host |
| `proof` | What PROVES it — a domain UUID, the name a VMID must still bear |
| `address` | WHERE the service listens. Empty is not "unreachable" |
| `alias` | The name a `~/.ssh/config` resolves on its own. For a remote-host VM this is NOT its address: that one only routes from the host, the alias carries the whole path |
| `host` | The record of the machine hosting it — empty locally. It is what lets a verb know it must go through someone else |

`handle_of(entry)` reads the shape the manifests have today. An entry
carrying `pve` lives on a Proxmox host; one carrying `lima` is an instance;
the others are local. It returns `None` when nothing is ADDRESSABLE — never
because a field is missing: a remote VM is addressed by its VMID and stays
commandable without a name, simply **disarmed**.

## Why the proof exists

A libvirt domain name is reused; a VMID is reassigned once freed. Deleting
"the 101" from a manifest written in March deletes whatever bears 101 today.
Every destructive verb therefore carries an identity guard that **stops**
when the key no longer bears that name — and `is_armed` says when there is
no proof to arm it with.

## Proven, and not proven

All three backends have run against a real machine, through the WHOLE
lifecycle: create, start, list, execute a command chain, stop, delete.
"Unproven" never meant doubtful — it meant that what the tool makes of the
rendered text had not been measured. `long_test/lima_confront.py` is what
lifted the mention on `lima` — not a code review.

That distinction earns its keep: the instance description the package
rendered parsed perfectly as YAML and did not start, because the `arch`
field has a vocabulary of its own — `x86_64` where the repository and the
image both say `amd64`. No amount of reading finds that; one boot does.

A backend absent from the table is unproven by default: doubt leans towards
the side that promises nothing.

```bash
# L'identité d'une fiche de manifeste, et ce qu'elle arme :
python3 -c "from script.vm import backend as B; \
  h = B.handle_of({'name': 'vm-a', 'uuid': 'abc'}); \
  print(h.backend, h.key, B.is_armed(h))"
```