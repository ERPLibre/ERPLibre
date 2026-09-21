
# Network posture

What a VM's network reaches, decided before the machine exists.

A posture is **data, not behaviour**: a row in a registry saying what the
network allows. Nothing in this package runs a command or prints a screen —
it renders text and returns tokens, which is what makes it testable without
a machine, a terminal or a privilege.

## The four postures, and what each one really holds

| Posture | Profile | What it holds |
|---|---|---|
| `open` | Sandbox | NAT. Nothing is confined, and that is the point |
| `connected` | VM Connecté | Ports bounded, destinations free: `53,123/udp`, `22,80,443/tcp` toward anywhere |
| `paranoid` | VM paranoid | Destinations bounded, taken from the site's address book |
| `local-only` | local-webui | Egress cut, and a web interface reachable from the host |

The **profile** is the name a human recognises; the **posture** is what the
spec carries. They are separated on purpose: it is what allows serving
something else on the same posture.

## The golden rule

The couple *(posture, real data)* is refused **before the machine exists** —
the only moment at which a refusal costs nothing. Three fields, and none is
deduced from the others:

- `install.prod` — WHERE it installs;
- `posture` — WHAT THE NETWORK reaches;
- `real_data` — WHETHER the machine carries real data.

Confusing them produces the two symmetric accidents: a demo mock-up talking
to the whole Internet because it is "not production", and a production
machine confined to the point of no longer being able to update itself.

Only a posture whose destinations are bounded, whose rules are enforced and
whose mechanism catches container traffic may carry real data. Today that is
`local-only` alone — and a screen that offers a posture the guard will refuse
makes you answer a dozen more questions before saying so.

## Where the rules are laid, per backend

| Backend | How | When |
|---|---|---|
| libvirt / QEMU | cloud-init `write_files`, or the installer's `late_command` | **before** first boot |
| Proxmox VE | pushed into the guest after creation | **after** first boot — hence an open window |
| Lima | instance `provision:` block, `mode: system` | at first boot |

Lima **refuses** `local-only`: user-mode networking always gives egress, and
no instance setting removes it. Promising otherwise would be the reassuring
name the registry forbids itself.

## What is not held, and says so

A mechanism silent about what it does not apply is what makes people believe
in a confinement that does not exist. Four tokens, a closed vocabulary:

- `no-rendering` — the posture states a policy that nothing installs;
- `reload-failure-unseen` — a failed reload on a later boot is not reported;
- `containers-unproven` — container traffic crosses FORWARD, and no
  confrontation has measured it yet;
- `boot-window-open` — the rules arrive only once the machine answers.

## The address book

`paranoid` names seven roles and the deployment REFUSES until each has an
address. The book lives in three files that merge; the one tracked by git is
**refused by construction**, because an IP address outside `private/` becomes
public on the first push of a fork.

```bash
# Ce qu'une posture rend, sans machine :
python3 -c "from script.posture import registry, rules; \
  print(rules.render_egress(registry.get_posture('connected'), ()))"
```