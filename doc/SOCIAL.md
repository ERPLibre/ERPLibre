
# Social networks

Feeds and posting built into the TODO CLI, beside the mail client and on the
same principles: a local cache that answers offline, a secret that lives in
the vault and never in a file, and nothing that leaves the machine except
what you ask to send.

Every `Social > ...` path below is shorthand for
`TODO > [3] Assistant > [3] Social networks > ...`.


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
