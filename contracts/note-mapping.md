# Note mobile → project.task mapping

## Field mapping

| Note mobile field      | project.task field    | Type             | Notes |
|------------------------|-----------------------|------------------|-------|
| *(no mobile id sent)*  | `id`                  | Integer (server) | Odoo ID stored in mobile SQLite `note_links`, per server and database, after first push |
| *(target, per server)* | `project_id`          | Many2one         | Chosen per server at first push (none = personal task), sent by `create` only; the server's last choice is offered first |
| `title`                | `name`                | Char             | Required |
| `done`                 | `state`               | Selection        | Odoo 17+ : `'1_done'` ↔ done=true ; `'01_in_progress'` ↔ done=false |
| `archived`             | `active`              | Boolean          | false = archived |
| `pinned`               | `priority`            | Selection        | `'1'` = pinned, `'0'` = normal |
| `tags`                 | `tag_ids`             | Many2many        | Matched by tag name; created if missing |
| entry `text`           | `description`         | Html             | Each entry → `<p>text content</p>` |
| entry `date`           | `date_deadline`       | Datetime         | First date entry only |
| entry `audio`          | `attachment_ids`      | ir.attachment    | + `<p>🎙️ Enregistrement audio</p>` in description |
| entry `photo`          | `attachment_ids`      | ir.attachment    | + `<p>📷 Photo</p>` in description |
| entry `video`          | `attachment_ids`      | ir.attachment    | + `<p>🎥 Vidéo</p>` in description |
| entry `geolocation`    | `geo_task_point`      | GeoMultiPoint    | All lat/lon → MultiPoint GeoJSON, sent only when `fields_get` finds the field (module `erplibre_mobile_todo`) ; `<p>📍 text — lat,lon — ISO_DATE</p>` in description |

## Note mobile → crm.lead (opportunity)

A note can also be sent as an opportunity, beside or instead of its task,
per server (picker boxes Task / Opportunity).

| Note mobile field      | crm.lead field     | Notes |
|------------------------|--------------------|-------|
| *(target)*             | `type`             | `'opportunity'`, create only |
| *(target)*             | `partner_id`       | Client chosen in the picker (name_search), create only, optional |
| *(target)*             | `expected_revenue` | Typed in the picker, create only, optional |
| `title`                | `name`             | |
| entries                | `description`      | Same HTML as the task, with the marker |
| `tags`                 | `tag_ids`          | `crm.tag`, matched by name, created if missing |
| first `date` entry     | `date_deadline`    | Date: the day only |
| `archived`             | `active`           | Create only: never written after, it would revive an opportunity marked lost |
| `done`, `pinned`       | —                  | Not mapped (no won/lost, no stars) |

## Note mobile → account.move (draft invoice)

A note can also be drafted as a customer invoice or a vendor bill, one per
server (picker box Draft invoice).

| Note mobile field      | account.move field  | Notes |
|------------------------|---------------------|-------|
| *(target)*             | `move_type`         | `out_invoice` or `in_invoice`, create only |
| *(target)*             | `partner_id`        | Partner chosen (name_search), optional on a draft, create only |
| *(target)*             | `invoice_date`, `ref` | Typed in the picker, create only |
| *(target)*             | `invoice_line_ids`  | Lines typed: label, quantity, unit price, optional product; create only |
| *(target)*             | other required fields | Asked by the dynamic form (fields_get + default_get), create only |
| *(target)*             | many2one to the task or lead | When a module adds one; else a message in each chatter |
| `title`, entries       | `narration`         | Title in bold, the HTML, the marker; the only field written after |
| `tags`, `done`, `pinned`, `archived` | —     | Not mapped |

## Note mobile → mail.activity

A note can schedule several activities per server, each on a record chosen
in the picker (a contact, an opportunity, a task, … or the note's own task
or opportunity).

| Note mobile field      | mail.activity field | Notes |
|------------------------|---------------------|-------|
| *(target)*             | `res_model_id`      | From `default_res_model` in the create context, create only |
| *(target)*             | `res_id`            | Record chosen (name_search), create only |
| *(target)*             | `activity_type_id`  | Chosen among mail.activity.type, create only; none: server default |
| *(target)*             | `date_deadline`     | Picker: the note's first date, else today + the type's delay; create only |
| *(target)*             | `user_id`           | Chosen among res.users, create only; none: the connected user |
| `title`                | `summary`           | |
| entries                | `note`              | Same HTML as the task, with the marker |
| `done`                 | —                   | `action_feedback`: the activity is marked done, once |
| `tags`, `pinned`, `archived` | —             | Not mapped |

## Note mobile → mail.message (message in a chatter)

A note can be posted, as a logged note, in the chatter of several records
per server, chosen in the picker.

| Note mobile field      | mail.message        | Notes |
|------------------------|---------------------|-------|
| *(target)*             | `model`, `res_id`   | Record chosen; the message is posted with `message_post` on it |
| `title`                | `body`              | First paragraph, in bold |
| entries                | `body`              | Same HTML as the task, then the marker |
| *(change)*             | `body`              | Edited through `/mail/message/update_content` when its hash changed |
| `done`, `tags`, `pinned`, `archived` | —     | Not mapped |

## Description HTML structure

Each note's `description` field is built by concatenating all entries in order:

```html
<!-- entry type=text -->
<p>Content of the text entry.</p>

<!-- entry type=text (another one) -->
<p>Another paragraph of notes.</p>

<!-- entry type=date -->
<p>📅 Date : 2026-03-29T14:30:00</p>

<!-- entry type=geolocation -->
<p>📍 Géolocalisation : 45.5017, -73.5673 — Bureau principal — 2026-03-29T14:35:00</p>

<!-- entry type=audio -->
<p>🎙️ Enregistrement audio — 2026-03-29T14:40:00</p>

<!-- entry type=photo -->
<p>📷 Photo — 2026-03-29T14:45:00</p>

<!-- entry type=video -->
<p>🎥 Vidéo — 2026-03-29T14:50:00</p>
```

## GeoMultiPoint format (geo_task_point)

All geolocation entries of a note are stored as a single GeoJSON MultiPoint:

```json
{
  "type": "MultiPoint",
  "coordinates": [
    [-73.5673, 45.5017],
    [-73.5789, 45.4972]
  ]
}
```

Order matches the order of geolocation entries. Coordinates are `[longitude, latitude]` per GeoJSON spec.
Timestamps and text descriptions are preserved in the HTML description `<p>` lines.

## Sync ID strategy

- Mobile does **not** send the note's internal id to Odoo.
- On first push to a server, the creation runs as an outbox operation
  (`sync_outbox`, kind `task.create`) with its own `client_uuid`; the task
  description ends with `<p><small>erplibre-mobile:{client_uuid}</small></p>`,
  kept on every later write.
- `project.task.create()` returns the Odoo `id` (integer).
- A retry of that operation first searches the marker (`description ilike`,
  archived included): one task found is adopted, none means create, several
  (a copy made on the server carries the marker too) block the operation
  until the user picks the task to link — a create whose answer was lost is
  not duplicated. The search runs no earlier than 3 minutes after the last
  create was sent, so a create still running on the server has committed.
- Mobile stores it in its local SQLite `note_links` table, keyed by the sync
  config id `url|username|database`: an id is only meaningful in the database
  that issued it.
- Subsequent pushes to that server use `project.task.write([[id], {...}])`,
  without `project_id`, so a task moved to another project on the server
  stays there; a push to another server creates and links that server's own
  task.
- Pull and poll read the tasks linked on the server by id, whatever their
  project.
- A write sends only the fields changed in the app since the last exchange:
  tags as added and removed (commands 4 and 3), so tags others set on a task
  of a shared project stay, and `state` only when done changed, so a state
  another user set (waiting, approved) stays. Pull copies tags back.
- Multiple mobile clients: each independently stores the same `id` — fully supported.

## Conflict resolution

Each link keeps a base: the note's and the record's values of each
mirrored field (title, text, tags, date, done, archived, pinned, as the
kind has them) at their last exchange. Pull, and each push before it
writes, merge field by field:

| Condition (per field, since the base) | Resolution |
|---------------------------------------|------------|
| Changed on the server only | The note takes the server's value |
| Changed in the app only | The push sends it, alone |
| Changed on both sides to the same value | Nothing to do |
| Changed on both sides to different values | Conflict: nothing is sent to that server until the user keeps the app's or the server's version |
| Pull changed a note linked on several servers | The other servers are queued, so they receive the new values |
| Record deleted on the server | The link is marked deleted; nothing is recreated unless the user confirms |

Text comes back as the record's paragraphs, replacing the note's text
entries; media, date and position entries stay, and the lines the app
writes from them, like the marker, are skipped. An activity's deadline
comes back into the note's date, but is never written from it.

## Tag resolution

1. Mobile sends tag names as strings.
2. SyncService calls `project.tags` `search_read` to find existing tags by name.
3. Missing tags: `project.tags.create()` before task create/write.
4. `tag_ids` in task payload uses integer IDs from step 2-3.
