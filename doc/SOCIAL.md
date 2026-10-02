
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
