# Media Browser — design plan

Status: **draft / not implemented**. Source of truth for the work that
turns the flat `MediaIndicator` dropdown into a real library browser
with tabs, grouping, sorting, search and a "what to play next" UX.

Scope is the GNOME extension only (`indicators/media.js`,
`lib/media-helpers.js`, `ui/media-dialog.js`, plus a new
`ui/media-library-dialog.js`). No driver / D-Bus changes.

## Goals

1. Browse a media catalogue grouped by **artist / author / album** in
   addition to the current Video / Audio split.
2. Sort by **last played**, **alphabetical**, **play count**, **rating**,
   **added**.
3. **Scrollable** list that does not break the GNOME PopupMenu theme.
4. **Tabs** between Films and Songs in the panel applet so the dropdown
   stays short.
5. Quick-start the right thing: surface "what I was watching", "what I
   left mid-way", "what I rated 4★+".
6. Pure-JS helpers so logic is unit-testable via `node --test`.

Non-goals for this iteration: thumbnails, online metadata fetch,
cross-device sync, playlists / queues, library import.

## Current state (pinned)

- One GSettings key `media` (string), JSON-serialised array of entries:
  `{id, name, url, episode, position, kind, last_played}` — see
  `lib/media-helpers.js::defaultMediaEntry`.
- `MediaIndicator` renders a flat `PopupMenu` split into two static
  sections (`— Videos (n) —`, `— Audio (n) —`).
- A `St.ScrollView` wrapper around rows was attempted and reverted: it
  rendered submenu items with broken theme colours on some setups
  (see comment around `indicators/media.js:99`).
- `MediaDialog` already supports auto-fill (`extractMediaInfo`) and a
  Video/Audio kind toggle.
- `mpv-state.js` exposes the live "playing" set used to prefix rows
  with `▶`.

## Data model — extended entry

`defaultMediaEntry` gains optional fields. All additions default to `''`
or `0` so existing entries keep working without migration code.

```js
{
  // existing
  id, name, url, episode, position, kind, last_played,

  // new
  artist:     '',   // author / director / band / channel
  album:      '',   // season name for video, album for audio
  year:       '',   // free string ('2023', '2023-04', '')
  genre:      '',
  rating:     0,    // 0..5 integer
  play_count: 0,    // int, ++'d on every _launch
  duration:   '',   // 'hh:mm:ss', filled when mpv watch_later is read
  added_at:   '',   // ISO when defaultMediaEntry first ran
  tags:       [],   // free strings, low priority
}
```

Backwards compatibility:

- Reads tolerate missing fields (use `??` everywhere, never `||` against
  numeric `0`).
- `serializeList` already round-trips arbitrary keys, no change needed.
- No schema bump in `org.gnome.shell.extensions.streamdeck-tiler.gschema.xml`
  — we keep the same `media` key.

`extractMediaInfo()` extends to fill `artist` / `album` from URLs that
already carry them (Spotify, Bandcamp, SoundCloud, Apple Music, Deezer,
Tidal). The dialog Auto-fill button surfaces these new fields the same
way it surfaces `name` / `episode` today.

## UI architecture — two surfaces

### A. Applet dropdown (fast path)

Stays a `PopupMenu` to keep theming sane. No `St.ScrollView` inside it.

Layout from top to bottom:

```
+ Add media…
⚙ Open prefs
─────────────────────────────
[ Films (24) ]  [ Musique (87) ]  [ Tout ]   ← tabs (St.Button row)
─────────────────────────────
▶ En cours              (entries currently in mpv-state)
⏱ Récents               (top 5 last_played desc)
↻ À finir               (position > 0 and not played in last 7 days)
★ Favoris               (rating >= 4, top 5)
─────────────────────────────
+ Ouvrir la bibliothèque…   → opens MediaLibraryDialog
```

- The tab row is built with `St.BoxLayout` of `St.Button`s wrapped in a
  `PopupMenu.PopupBaseMenuItem` so PopupMenu still owns layout.
- Active tab persisted under a new GSettings key `media-active-tab`
  (string `video|audio|all`, default `all`).
- Section headers stay as non-reactive `PopupMenuItem` lines (pattern
  already used).
- Each smart section caps at 5 rows; overflow stays visible by clicking
  "Open library".

### B. MediaLibraryDialog (full browser)

New `ui/media-library-dialog.js`, a `ModalDialog` that owns the heavy
list. Three columns:

```
┌──────────────┬──────────────────────┬─────────────┐
│ Sidebar      │ List                 │ Detail      │
│              │                      │             │
│ Tabs         │ scrollable           │ name        │
│ Group by     │ collapsible groups   │ artist /    │
│ Sort by      │ row = entry          │ album / yr  │
│ Search       │ click → detail       │ rating ★★★  │
│ Filters      │ context menu actions │ play count  │
│              │                      │ last played │
│              │                      │ position    │
│              │                      │ [Browser]   │
│              │                      │ [mpv]       │
│              │                      │ [VLC]       │
│              │                      │ [Spotify]   │
│              │                      │ [Edit]      │
│              │                      │ [Delete]    │
└──────────────┴──────────────────────┴─────────────┘
```

- `St.ScrollView` is safe here because we own the dialog and pick the
  styles. No PopupMenu interference.
- Sidebar:
  - **Tabs**: Films / Musique / Tout (mirrors applet).
  - **Group by**: `Aucun | Artiste | Album | Genre | Année`.
  - **Sort by**: `Dernier écouté ↓ | A–Z | Plus joué | Note | Ajouté`.
  - **Search**: `St.Entry`, focused on open, live filter on
    `name + artist + album` (case-insensitive substring).
  - **Filters**: checkboxes `Non-vus`, `À finir`, `Favoris seulement`.
- List:
  - Sections are collapsible; expanded state stored per-group in a
    Map for the lifetime of the dialog (not persisted — cheap).
  - Each row shows `name · episode · position · 📅 last_played` plus a
    progress bar `▮▮▮▮▯` when `duration` is known.
  - Keyboard: `↑/↓` move focus, `Enter` plays default (last used
    player per entry), `1–5` rates, `Del` deletes (with confirm),
    `/` jumps to search.
- Detail panel updates on selection. Default-focus is the play button.

## Pure helpers — `lib/media-helpers.js`

All testable through `node --test`. New exports:

```js
groupBy(entries, key)
  // key in {'', 'artist', 'album', 'genre', 'year'}; '' => single
  // group ''. Returns Map<string, entry[]>; empty values bucket
  // under '' so we can label them "(sans artiste)".

sortEntries(entries, mode)
  // mode in {'last_played', 'alpha', 'play_count', 'rating', 'added'}.
  // 'last_played' descending, '' goes last.
  // 'alpha' uses localeCompare with sensitivity:'base'.
  // 'play_count', 'rating' descending, ties broken by 'last_played'
  // then 'alpha'.

filterEntries(entries, {kind, query, unwatched, unfinished, favourites})
  // kind: 'video' | 'audio' | undefined.
  // query: trimmed lowercase substring match on name/artist/album.
  // unwatched: !last_played.
  // unfinished: position truthy and last_played older than 7 days.
  // favourites: rating >= 4.

formatProgress(position, duration)
  // returns '▮▮▮▮▯ 78%' or '' when duration empty.
```

`buildMediaLabel` keeps its current shape; the library row uses a
richer renderer that lives in the dialog.

## Smart sections — definitions

| Section     | Predicate                                                        |
| ----------- | ---------------------------------------------------------------- |
| ▶ En cours  | `id` present in `listMpvEntriesSync()`                           |
| ⏱ Récents   | top N by `last_played` desc, ignoring entries with empty value   |
| ↻ À finir   | `position` truthy AND `last_played` older than 7 days            |
| ★ Favoris   | `rating >= 4`, top N by `last_played` desc                       |

`N = 5` for the applet dropdown. The library has no cap.

## Persistence

- Catalogue: existing GSettings key `media` (JSON string).
- New GSettings keys (string, default empty/safe):
  - `media-active-tab` (`video|audio|all`)
  - `media-sort-mode` (`last_played|alpha|play_count|rating|added`)
  - `media-group-by` (`none|artist|album|genre|year`)
- Library expanded-group state is **not** persisted (lifetime of
  dialog only).

## Behaviour wiring

- `_launch` now also `play_count++` and stamps `last_played` (already
  stamps it). Single GSettings write per launch.
- `_updateMpvPosition` already updates `position`; extend it to also
  capture `duration` from the `mpv` watch-later file when present
  (regex `/^\s*duration=([\d.]+)/m`, format via `formatPosition`).
- Adding a media via `MediaDialog` stamps `added_at = new Date().toISOString()`.

## Migration

None required. New fields default to falsy and every read site uses
nullish-coalescing. Downgrading does not lose data because
`serializeList` round-trips unknown keys.

## Tests

New cases in `test/lib-media-helpers.test.mjs`:

- `groupBy` empty input, single group, multi-group, blank values bucket.
- `sortEntries` last_played puts empty last, alpha is locale-aware,
  numeric ties fall back to alpha.
- `filterEntries` AND-composition of all flags, query trims and is
  case-insensitive.
- `formatProgress` edge cases (`duration=''`, `position > duration`).

`extractMediaInfo` gets new cases for Spotify album → `artist+album`,
Bandcamp track → `artist+album`, SoundCloud set → `artist+album`.

## Commit plan (proposed sequence)

- [ ] **[ADD] media: extra fields (artist/album/rating/play_count/duration/added_at)**
      — extend `defaultMediaEntry`, no UI yet, tests round-trip new keys.
- [ ] **[ADD] media-helpers: groupBy / sortEntries / filterEntries / formatProgress**
      — pure JS + `node --test` coverage.
- [ ] **[IMP] media-helpers: extractMediaInfo fills artist/album for music URLs**
      — Spotify, Bandcamp, SoundCloud, Apple Music, Deezer, Tidal.
- [ ] **[IMP] media: tabs Video/Audio/All in applet dropdown**
      — `media-active-tab` GSettings key, button row above sections.
- [ ] **[ADD] media: smart sections (En cours / Récents / À finir / Favoris)**
      — capped at 5 each, replace flat Video/Audio listing.
- [ ] **[ADD] ui/media-library-dialog: scrollable browser with sidebar**
      — search, group-by, sort, expand/collapse groups.
- [ ] **[ADD] media: detail pane with rating + per-entry actions**
      — keyboard shortcuts (↑/↓, Enter, 1–5, Del, /).
- [ ] **[IMP] media: capture duration from mpv watch_later + progress bar**
      — extend `_updateMpvPosition`, render `formatProgress`.
- [ ] **[IMP] media-dialog: auto-fill artist/album fields when known**
      — surface in dialog UI under URL row.

Each commit stays compilable, ships its own tests, and keeps the
applet usable on its own.

## Risks / open questions

- **PopupMenu + custom tab row**: `St.Button` inside `PopupBaseMenuItem`
  may swallow keyboard navigation. Fallback: render tabs as three
  `PopupMenuItem`s with accent style on the active one.
- **Dropdown width**: long names in "Récents" can stretch the panel.
  Truncate at ~40 chars and use `attachHoverTooltip` for the full text
  (helper already exists in `lib/badges.js`).
- **Library scrolling**: `St.ScrollView` works reliably *outside* a
  PopupMenu — confirmed by other dialogs in the project. Watch out for
  focus traps when search is active.
- **Performance**: 1000+ entries are still cheap (single in-memory
  array). Re-render the whole list on filter change; no diffing
  needed at this size.
- **i18n**: every new label goes through `_()` and gets added to
  `po/streamdeck-tiler.pot` via the existing extraction step.
- **Scope creep**: thumbnails, queues and online metadata are
  explicitly out — don't sneak them in mid-PR.
