
# Forge — Forgejo and Gitea

Four modules, one division: **what decides never prints, and what prints
never decides.** That separation is what makes a verdict verifiable without a
forge, and what lets the same code serve a menu, a script and a test.

## The secret is not in the profile

A forge profile holds its base URL, its owner account and its TLS posture —
in readable JSON. **The API token lives in the KeePassXC vault.** A profile
can therefore be read, shown, compared and versioned at a customer's site
without ever handing over the means to write into the forge.

## Saying WHY, not just "it failed"

The API returns a named verdict, from a closed vocabulary: `ok`, `no-token`,
`bad-token`, `localnetwork-refused`, `not-found`, `already-exists`,
`tls-untrusted`, `unreachable`, `refused`.

Two of them exist because the naive answer sends you to the wrong place:

- **`localnetwork-refused`** — Forgejo refuses to mirror a repository whose
  address resolves inside a private range. Missing that phrasing makes you
  conclude the token is wrong, and you go and reissue a token that was fine.
- **`tls-untrusted`** — a lab forge's self-signed certificate is the common
  case, and it is fixed by trusting the authority, not by changing token.

Page size is asked for **explicitly**: a client that relies on the server's
default stops after one page without saying so.

## The mirror: show the gap before creating anything

`mirror.plan(declared, present)` takes two lists of names and returns a plan.
It **calls nothing**. That is what makes reconciling two hundred names
verifiable without a forge, and what allows SHOWING the plan before a single
repository is created.

## The address decides who can read the token

An API token travels in a header. Validating a forge's base URL is therefore
not cosmetic: it decides who receives the token. That check lives here, next
to the forge, and not in the shared format module.

```bash
# Le plan d'un miroir, sans joindre aucune forge :
python3 -c "from script.forge import mirror; \
  p = mirror.plan(['a', 'b'], ['a']); print(p)"
```