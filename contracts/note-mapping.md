# Note mobile → project.task mapping

## Field mapping

| Note mobile field      | project.task field    | Type             | Notes |
|------------------------|-----------------------|------------------|-------|
| *(no mobile id sent)*  | `id`                  | Integer (server) | Odoo ID stored in mobile SQLite as `odoo_id` after first push |
| `title`                | `name`                | Char             | Required |
| `done`                 | `state`               | Selection        | `'done'` ↔ done=true ; `'01_in_progress'` ↔ done=false |
| `archived`             | `active`              | Boolean          | false = archived |
| `pinned`               | `priority`            | Selection        | `'1'` = pinned, `'0'` = normal |
| `tags`                 | `tag_ids`             | Many2many        | Matched by tag name; created if missing |
| entry `text`           | `description`         | Html             | Each entry → `<p>text content</p>` |
| entry `date`           | `date_deadline`       | Datetime         | First date entry only |
| entry `audio`          | `attachment_ids`      | ir.attachment    | + `<p>🎙️ Enregistrement audio — ISO_DATE</p>` in description |
| entry `photo`          | `attachment_ids`      | ir.attachment    | + `<p>📷 Photo — ISO_DATE</p>` in description |
| entry `video`          | `attachment_ids`      | ir.attachment    | + `<p>🎥 Vidéo — ISO_DATE</p>` in description |
| entry `geolocation`    | `geo_task_point`      | GeoMultiPoint    | All lat/lon → MultiPoint GeoJSON ; `<p>📍 text — lat,lon — ISO_DATE</p>` in description |

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

- Mobile does **not** send its internal UUID to Odoo.
- On first push: `project.task.create()` returns the Odoo `id` (integer).
- Mobile stores it as `odoo_id` in its local SQLite `notes` table.
- Subsequent pushes use `project.task.write([[odoo_id], {...}])`.
- Multiple mobile clients: each independently stores the same `odoo_id` — fully supported.

## Conflict resolution

| Condition | Resolution |
|-----------|------------|
| `write_date` (Odoo) > `last_synced_at` (mobile) | Odoo wins — pull overwrites mobile |
| Mobile modified since `last_synced_at`, Odoo not changed | Mobile wins — push |
| Both modified since last sync | Odoo wins (last-write-wins, v1) |

## Tag resolution

1. Mobile sends tag names as strings.
2. SyncService calls `project.tags` `search_read` to find existing tags by name.
3. Missing tags: `project.tags.create()` before task create/write.
4. `tag_ids` in task payload uses integer IDs from step 2-3.
