---
name: commit
description: "ERPLibre commit: OCA tag, bilingual body, Assisted-by trailer per AI_POLICY.md."
disable-model-invocation: true
allowed-tools:
  - Bash(git add:*)
  - Bash(git status:*)
  - Bash(git commit:*)
  - Bash(git diff:*)
  - Bash(git log:*)
  - Bash(python3:*)
---

## Context

- Git status: !`git status`
- Full diff: !`git diff HEAD`
- Current branch: !`git branch --show-current`
- Last 5 commits (for style reference): !`git log --oneline -5`

## Task

Write a commit that satisfies `AI_POLICY.md` — the OCA generative AI policy
ERPLibre adopts — and the conventions below.

### Resolve the model — `{MODEL}`

Run this first. It reads the model from the CURRENT session transcript, which
is the only source that stays right when the model is switched mid-session
with `/model` or a CLI flag:

```bash
python3 -c "
import glob, json, os, sys
sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
hits = glob.glob(os.path.expanduser('~/.claude/projects/*/%s.jsonl' % sid)) if sid else []
mid = ''
for path in hits[:1]:
    with open(path) as fh:
        for line in fh:
            try:
                m = json.loads(line).get('message', {}).get('model', '')
            except Exception:
                continue
            if m and not m.startswith('<'):
                mid = m
if not mid:
    sys.exit('UNKNOWN')
mid = mid.removeprefix('claude-')
parts = [p for p in mid.split('-') if not (len(p) == 8 and p.isdigit())]
print('Claude %s %s' % (parts[0].capitalize(), '.'.join(parts[1:])))
"
```

It prints the trailer value: `Claude Opus 5`, `Claude Sonnet 4.6`,
`Claude Haiku 4.5`. There is deliberately no fallback name — on `UNKNOWN`,
use the model you know you are running as, and never a value read from a
settings file: `~/.claude/settings.json` usually has no `model` key at all,
so it would quietly declare the default instead of the truth.

### Tags

| Tag | Usage |
|-----|-------|
| `[UPD]` | Update existing code, data or configuration |
| `[FIX]` | Bug fix |
| `[ADD]` | New module, file or capability |
| `[IMP]` | Improvement to something that already works |
| `[REF]` | Refactoring, no observable behaviour change |
| `[REM]` | Remove code or module |
| `[MOV]` | Move or rename |
| `[I18N]` | Translations |

The first five cover every one of the last 400 commits. Reach for `[REM]`,
`[MOV]` or `[I18N]` only when one of them genuinely fits better.

### Format

```
[TAG] scope: short description in imperative mood

Explain WHY the change was made — the diff already shows what. Name the
symptom that led to it, and what was measured rather than assumed.
Wrap at 80 characters.

--- FR ---

The same body, translated.

Assisted-by: {MODEL}
```

### The subject line

The subject is read a hundred times for every time the body is read: in
`git log --oneline`, in a blame, in a release note, in a bisect. It has one
job — say what the code is about.

**The test.** Read the subject alone, with no diff and no body. Can you say
which part of the system it concerns, and what is now different about it? If
not, it is not finished.

**Name the thing, then what changed about it.** The symptom, the quoted error
and the metaphor are EVIDENCE, and evidence belongs in the body. A subject
built on them reads well and tells the next reader nothing:

| Instead of | Write |
|-----------|-------|
| `[FIX] nettoyage : les enfants s'en vont avec leur rebond` | `[FIX] nettoyage : les entrées ssh qui rebondissent par une VM effacée` |
| `[FIX] proxmox : « il manque le stockage » était le symptôme, pas la cause` | `[FIX] proxmox : signaler pmxcfs à terre, et non « aucun stockage »` |
| `[FIX] migration: un module fautif n'emporte plus tout le lot` | `[FIX] migration: isoler l'échec d'un module dans la désinstallation` |

The scope is not the subject. `proxmox` says WHERE; the words after the colon
must say WHAT. A subject that works with its scope removed is usually the
right one.

**Summarise the whole commit, not its largest piece.** When the work has two
faces — a guard moved and the check that proves it, a screen and the service
under it — the subject covers both or the commit should have been two. If the
only honest subject needs an `and` joining two unrelated things, split it.

**It must be complete in 72 characters.** A subject cut mid-phrase by
`--oneline` has failed at the one place it is read most. Write it to fit
rather than trimming it afterwards: drop the adjectives, keep the nouns.

### Keep it short

The body answers one question: why was this necessary. Stop once it is
answered — the reader owes you nothing beyond that.

**Ten lines per language. Fifteen is already long.** Past that, the reasoning
belongs in a document or a code comment, and the commit points at it. The
budget is per language: bilingual doubles everything, so it buys terseness,
it does not excuse length.

Cut, in this order:

- Anything the diff already says. `adds function X` is visible; `X because
  the DHCP lease can be stale` is not.
- Headings and bullet lists. If the change really needs sections, it needs
  several commits.
- Every clause that would not change what a reader does: no `this commit`,
  no `I decided to`, no summary of the summary, no restating the subject.

Keep, always: the symptom that led to the change, the figure you measured
rather than assumed, and one line naming what you verified and how. A single
`Checked: 4 jobs, 1.63 s at parallelism 1 vs 0.58 s at 4` is worth three
paragraphs of prose.

### Bilingual body

Every AI-assisted commit carries its body twice. Write it first in whichever
language you were thinking in, then the marker, then the translation.

The marker names the language of what FOLLOWS it: `--- FR ---` after an
English body, `--- EN ---` after a French one. One marker per commit, never
both.

Translate, do not re-summarise: a reader of either language must get the same
reasoning, the same measured figures and the same caveats.

### The Assisted-by trailer

`AI_POLICY.md` makes this binary — there was AI involvement or there was not,
with no threshold to judge. Anything from a single suggestion to fully
autonomous coding means the trailer, and it says nothing about the quality of
the work.

- One `Assisted-by:` line per model. A session that switched models declares
  each of them, one line each.
- NEVER name an AI in `Co-authored-by:`: authorship of a work by a machine is
  legally undefined. That field is for other HUMANS who worked on the change.
  You are already the author, so never co-author yourself.
- No blank line between trailers.

### Rules

- Subject: imperative mood, **72 characters maximum**, aim for 50.
- `scope` is the Odoo technical module (`sale_order`, `account`, `stock`) or
  the area of the repository (`script todo`, `qemu ssh`, `migration`).
- The commit stands on its own: state what was verified, and how. If a claim
  was not checked, say so rather than implying it was.
- If you cannot explain and defend every line, do not commit it.

### Size and pace

A patch under 30 lines in a single file is the reference point. Past ~500
lines the policy asks for prior agreement with a maintainer — say so instead
of committing quietly. When several unrelated modules are touched, propose
splitting into separate commits before writing anything.

### Execute

The timezone comes from the system, as it should: nothing is forced here, so
each contributor's commits carry their own zone. If yours land at `+0000`,
the machine itself is on UTC — common on a server or a VM — and the fix
belongs there, `sudo timedatectl set-timezone <Area/City>`, because it
affects every commit and not just this one.

The identity is passed explicitly with `-c`, which sets the author AND the
committer. `--author` alone sets only the author, and a checkout with no
configured `user.email` then fails on the committer.

Use a heredoc rather than `-m`: a body with quotes, backticks or accented
characters survives it unharmed.

```bash
git add -A
git -c user.name="Your Name" -c user.email="your@email.com" commit -F - <<'MSG'
[TAG] scope: description

Explain WHY here.

--- FR ---

The same body, translated.

Assisted-by: {MODEL}
MSG
```
