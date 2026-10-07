
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
