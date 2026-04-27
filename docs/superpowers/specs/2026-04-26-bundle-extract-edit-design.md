# Bundle Pipeline: tar.gz Lazy Extract + Edit Mode — Design

- **Status**: Draft
- **Date**: 2026-04-26
- **Author**: Mathieu Benoit (brainstormed with Claude)
- **Target**: `mobile/erplibre_home_mobile/`
- **Scope**: Replaces the current loose-file public bundle of 138 manifest repos with per-repo `.tar.gz` archives extracted lazily on first user view. Adds an opt-in "edit mode" that promotes a read-only extraction to a persistent, git-backed editable copy with traceable diffs vs the shipped baseline. Hardens the existing `bundleSourcePlugin` against filesystem flakiness.

## 1. Goals

1. **Stop shipping thousands of loose source files** in the APK. Today the build copies ~5 000–15 000 files from 138 manifest repos into `src/public/repos/`. This makes `cap sync` slow, the APK index large, and inflicts ENOENT/ENOTEMPTY race conditions on the build pipeline whenever symlinks or stale state exist in `src/public/`.
2. **Lazy-extract on first view**. The Code tool's user usually browses a handful of repos. Only those should hit disk; the rest stay as a single archive in APK assets.
3. **Editable mode with git tracking**. When the user wants to modify a file, escalate the repo to a persistent editable copy with a baseline git commit, so every edit shows up in `git diff` against the original shipped state. Reset and commit operations must be available from the app.
4. **Robust build pipeline**. The plugin must survive broken symlinks, stale `src/public/` state, and concurrent file changes during build. No more aborted builds from filesystem flakes.
5. **Zero new bundle weight at startup**. Decompression uses the WebView's native `DecompressionStream` (gzip). No JS gunzip dependency. The git layer (`isomorphic-git`) is loaded lazily via dynamic `import()` only when the user first enters edit mode.

## 2. Non-Goals

- Replacing the WebView's `fetch()` with anything heavier for the read-only case. `Filesystem.readFile` from the extracted Cache directory is enough.
- Network operations against remote git (clone, push, pull). Only **local** git ops (init, add, commit, status, diff, log, reset, checkout) — the baseline is shipped in the APK; edits are local.
- Migrating the **app's own source bundle** (`src/public/repo/`) to the same lazy/editable model in this iteration. It stays loose for now; same model can be applied later as a follow-up. (Footprint: 297 files, ~7 MB — small, stable.)
- LFS, submodules, signed commits. The 138 manifest repos use none of these.
- Online conflict resolution. If the shipping baseline changes (after `npm run build`), we currently overwrite a non-editable extraction; for editable repos the user can `resetAll()` to discard edits and re-promote, but we do not auto-merge.

## 3. Decisions Log

| # | Decision | Choice |
|---|----------|--------|
| 1 | Default extraction location | **`Cache`** (Capacitor `Directory.Cache`) — ephemeral, OS may reclaim, re-extract on next view |
| 2 | Editable extraction location | **`Documents`** (Capacitor `Directory.Data`) — persistent across reinstalls (within the same app id) |
| 3 | Decompression | Native `DecompressionStream('gzip')` — Web Streams API, available on Android WebView ≥ 80 (we target minSdk 24 / Android 7+ where WebView has been auto-updated past 80 since 2020) |
| 4 | Tar parser | Inline TS, ~200 lines, zero deps |
| 5 | Edit mode VCS | **`isomorphic-git`** (~150 KB gzipped, lazy-imported) with a custom Capacitor `Filesystem` adapter |
| 6 | App's own source bundle (`repo/`) | **Stays loose** in this iteration. Can be archived later. |
| 7 | Build-time tar.gz tool | Shell `tar -czf` via Node `child_process` — fastest, native, available on every dev machine; falls back to `node-tar` npm package if shell unavailable |
| 8 | Promotion trigger | User action ("Edit" button in Code tool); never automatic |

## 4. Architecture

### 4.1 File layout

```
mobile/erplibre_home_mobile/
├── src/
│   ├── public/
│   │   ├── repo/                           # App source (loose, unchanged)
│   │   ├── repos/
│   │   │   ├── manifest.json               # Now lists archive URL per project
│   │   │   ├── github-com-OCA-web-api.tar.gz
│   │   │   ├── github-com-OCA-website.tar.gz
│   │   │   └── ... × 138
│   │   └── ...
│   ├── services/
│   │   ├── bundleCodeService.ts            # Refactored: routes through extractor
│   │   ├── codeService.ts                  # Unchanged contract
│   │   ├── repoExtractorService.ts         # NEW: tar.gz → Cache extract
│   │   ├── repoEditService.ts              # NEW: Cache → Documents promote + git baseline
│   │   ├── editableCodeService.ts          # NEW: read/write + git ops on Documents copy
│   │   └── git/
│   │       └── capacitorFsAdapter.ts       # NEW: Node-fs-shaped wrapper around @capacitor/filesystem
│   ├── utils/
│   │   ├── tarParser.ts                    # NEW: streaming tar reader
│   │   └── decompressGzip.ts               # NEW: thin DecompressionStream wrapper
│   ├── models/
│   │   ├── manifestProject.ts              # NEW: shared types
│   │   └── gitTypes.ts                     # NEW: GitStatus / GitCommit / GitDiffHunk
│   └── __tests__/
│       ├── tarParser.test.ts
│       ├── repoExtractorService.test.ts
│       ├── repoEditService.test.ts
│       └── editableCodeService.test.ts
└── vite.config.ts                          # Hardened + tar.gz generation
```

### 4.2 Build pipeline (vite.config.ts)

For each manifest project that exists locally:

```
1. Walk source dir with existing copy filters (BINARY_EXT, MANIFEST_SKIP_DIRS, MAX_BUNDLE_FILE_BYTES)
2. Collect file list into BundleEntry[]
3. Stage filtered files into a temp dir (os.tmpdir/erplibre-bundle-{slug})
4. Write `index.json` at temp root listing files
5. Spawn `tar -czf <out>/{slug}.tar.gz -C <temp> .`
6. Remove temp dir
```

For the read-only path the runtime needs to know the entry list before extracting (so the Code tool can show a directory tree without unpacking). So `index.json` lives **inside** the archive at the root, and is also written **alongside** the archive as `{slug}.index.json` for fast pre-fetch.

`manifest.json` schema becomes:

```json
[
  {
    "url": "https://github.com/OCA/web-api",
    "name": "OCA/web-api",
    "path": "addons/OCA_web-api",
    "slug": "github-com-OCA-web-api",
    "revision": "18.0",
    "archive": "repos/github-com-OCA-web-api.tar.gz",
    "indexUrl": "repos/github-com-OCA-web-api.index.json",
    "fileCount": 174,
    "uncompressedBytes": 1234567,
    "compressedBytes": 234567
  }
]
```

### 4.3 Plugin hardening (Phase 1)

Three known fs flakes to address:

```
A. ENOENT on stat during readdir (broken symlink)
   → already wrapped in `copyDirToBundle`; extend to top-level `readdirSync` calls.

B. ENOTEMPTY on rmSync(reposOutDir)
   → caused by stale state from interrupted previous build, sometimes a
     symlink in src/public/repos/{slug}/ to a moving target.
   → switch to `rmSync(reposOutDir, { recursive: true, force: true,
     maxRetries: 5, retryDelay: 100 })`.

C. ENOENT during top-level readdirSync(root) (rare)
   → wrap in try/catch with informative message; re-throw only after
     a single retry.
```

`bundleSourcePlugin` also gains a `preserveExistingArchives` flag (default off): when on, it skips re-archiving repos whose source dir hasn't changed since the existing `.tar.gz`'s mtime, dramatically speeding incremental dev builds.

### 4.4 Runtime: read-only extraction flow

```
User opens Code tool → selects "OCA/web-api"
  ↓
BundleCodeService.openRepo("github-com-OCA-web-api")
  ↓
RepoExtractorService.ensureExtracted(slug, archiveUrl, indexUrl)
  ├─ Check sentinel: Cache/repos/{slug}/.extracted exists? → return early
  ├─ Else:
  │   1. fetch(archiveUrl) → ReadableStream
  │   2. .pipeThrough(new DecompressionStream('gzip')) → ungzipped tar bytes
  │   3. tarParser.parse(stream) → for each entry { name, size, isDir, content }:
  │        Filesystem.writeFile({
  │          path: `repos/${slug}/${name}`,
  │          directory: Directory.Cache,
  │          data: btoa(content),  // base64
  │        })
  │   4. Filesystem.writeFile sentinel `.extracted` with timestamp
  └─ Returns: `Cache/repos/{slug}` URI
  ↓
BundleCodeService now reads files from extracted Cache via Filesystem.readFile()
```

`Filesystem.writeFile` writes serially per file. For a repo with 1 000 files this is the slow path (~1–5 s on a mid-range device). Two optimizations:

- **Batch by directory**: pre-create directories with `Filesystem.mkdir` once per dir, then write files.
- **Parallelize file writes** with `Promise.all` chunks of 16 — the bottleneck is base64 encoding + JNI marshalling, partly parallel-friendly.
- **Progress events**: `RepoExtractorService` emits `extractProgress({slug, written, total, currentPath})` events so the UI can show a progress bar.

### 4.5 Runtime: edit mode promotion

```
User clicks "Edit this repo" in Code tool
  ↓
RepoEditService.promoteToEditable(slug)
  ├─ ensureExtracted(slug)  (idempotent; no-op if already extracted)
  ├─ Recursively copy Cache/repos/{slug}/ → Documents/repos/{slug}/
  │   (with mkdir + writeFile per file, same as extraction)
  ├─ Lazy `import()` isomorphic-git
  ├─ Initialize git repo in Documents/repos/{slug}/.git via the
  │   capacitorFsAdapter
  ├─ git.add({fs, dir, filepath: '.'})
  ├─ git.commit({fs, dir, message: "baseline: shipped via APK build {build_id}",
  │              author: {name: 'ERPLibre Mobile', email: 'app@local'}})
  └─ Persist editable state in SQLite (the encrypted DB already in use):
       INSERT INTO editable_repos(slug, baseline_sha, promoted_at, build_id)
  ↓
BundleCodeService now routes to EditableCodeService for this slug
```

### 4.6 Runtime: editable file ops

`EditableCodeService` exposes:

```typescript
interface EditableCodeService {
    listDir(path: string): Promise<DirEntry[]>;
    readFile(path: string): Promise<string>;
    writeFile(path: string, content: string): Promise<void>;
    deleteFile(path: string): Promise<void>;

    status(): Promise<GitStatus>;                        // {modified, untracked, staged}
    diff(filepath?: string): Promise<GitDiffHunk[]>;     // unified diff, optionally per-file
    log(opts?: {limit?: number}): Promise<GitCommit[]>;

    commit(message: string): Promise<string>;            // returns SHA
    resetFile(filepath: string): Promise<void>;          // checkout HEAD -- filepath
    resetAll(): Promise<void>;                           // reset --hard HEAD
    unpromote(): Promise<void>;                          // delete Documents copy entirely
}
```

All git ops go through `isomorphic-git` with the `capacitorFsAdapter`. Reads/writes for non-git operations go directly through `@capacitor/filesystem`.

### 4.7 isomorphic-git filesystem adapter

`isomorphic-git` accepts a `fs` object that mimics Node's `fs.promises`:

```typescript
interface IsoGitFs {
    readFile(path: string, opts?: {encoding?: string}): Promise<Uint8Array | string>;
    writeFile(path: string, data: Uint8Array | string, opts?: {encoding?: string; mode?: number}): Promise<void>;
    unlink(path: string): Promise<void>;
    readdir(path: string): Promise<string[]>;
    mkdir(path: string, opts?: {recursive?: boolean}): Promise<void>;
    rmdir(path: string): Promise<void>;
    stat(path: string): Promise<FsStat>;
    lstat(path: string): Promise<FsStat>;     // optional, can fall back to stat
    readlink?(path: string): Promise<string>; // optional
    symlink?(...): Promise<void>;             // optional
}
```

Our `capacitorFsAdapter.ts` wraps `@capacitor/filesystem` and translates each call. Symlinks and readlink are no-ops (manifest repos don't use them). Path semantics are absolute — adapter prefixes with `Documents/` and uses `Directory.Data`.

### 4.8 Tar parser

Plain TS, no deps:

```typescript
export interface TarEntry {
    name: string;
    size: number;
    isDirectory: boolean;
    isFile: boolean;
    mode: number;
    content?: Uint8Array;  // present only if isFile
}

export async function* parseTarStream(
    stream: ReadableStream<Uint8Array>
): AsyncIterable<TarEntry>;
```

Handles ustar header parsing (octal ASCII size, type flag, prefix+name), 512-byte blocks, padding, end-of-archive markers (1024 zero bytes).

### 4.9 Decompression helper

```typescript
export function gunzipStream(
    input: ReadableStream<Uint8Array>
): ReadableStream<Uint8Array> {
    return input.pipeThrough(new DecompressionStream('gzip'));
}

export async function gunzipBytes(input: Uint8Array): Promise<Uint8Array>;
```

The streaming form is what `repoExtractorService` uses. The eager form is for tests.

## 5. Data Models

```typescript
// models/manifestProject.ts
export interface ManifestProject {
    url: string;
    name: string;
    path: string;
    slug: string;
    revision: string;
    archive: string;            // "repos/{slug}.tar.gz"
    indexUrl: string;           // "repos/{slug}.index.json"
    fileCount: number;
    uncompressedBytes: number;
    compressedBytes: number;
}

export interface BundleEntry {
    path: string;
    type: "file" | "dir";
    size?: number;
}

// models/gitTypes.ts
export interface GitCommit {
    sha: string;
    message: string;
    author: { name: string; email: string };
    date: string;          // ISO 8601
    parentShas: string[];
}

export interface GitStatus {
    modified: string[];
    untracked: string[];
    staged: string[];
    deleted: string[];
}

export interface GitDiffHunk {
    filepath: string;
    oldStart: number;
    newStart: number;
    lines: GitDiffLine[];
}

export interface GitDiffLine {
    type: "context" | "add" | "del";
    content: string;
}
```

## 6. SQLite schema change

One new table tracks edit-mode state:

```sql
CREATE TABLE IF NOT EXISTS editable_repos (
    slug          TEXT PRIMARY KEY,
    baseline_sha  TEXT NOT NULL,
    build_id      TEXT NOT NULL,        -- build identifier used at extraction time
    promoted_at   INTEGER NOT NULL,     -- epoch ms
    head_sha      TEXT                  -- updated on every commit
);
```

A new migration is added in the project's existing migration framework (`src/services/migrationService.ts`).

## 7. Error Handling

| Condition | Detection | Action |
|-----------|-----------|--------|
| Archive download fails | `fetch` → !ok | Throw `BundleNotShippedError(slug)`; UI shows a "rebuild app" hint |
| Archive corrupt (gunzip throws) | `DecompressionStream` errors | Throw `BundleCorruptError(slug)`; user can manually re-extract via UI |
| Tar parse error mid-stream | `parseTarStream` throws | Same as corrupt — abort extraction, sentinel never written, retry on next view |
| `Filesystem.writeFile` fails (disk full) | exception | Abort, surface error, sentinel never written |
| Edit promote: copy fails partway | exception | Roll back: delete partial `Documents/repos/{slug}` |
| Git init fails | isomorphic-git throws | Roll back: delete `Documents/repos/{slug}/.git` and the persisted SQLite row |
| Commit on a slug that's not editable | `isEditable() === false` | Reject with `RepoNotEditableError(slug)` |
| `unpromote` while git has uncommitted edits | check `status()` first | Require force flag OR confirm dialog at UI layer |
| Read-only `writeFile` attempt | `EditableCodeService` not instantiated | TypeScript prevents it; runtime: `BundleCodeService` throws `ReadOnlyError` |
| Cache evicted by OS | sentinel disappears | Next `ensureExtracted()` re-extracts transparently |
| Sentinel exists but extracted dir empty | check file count | Treat as evicted; re-extract |

## 8. Testing

### 8.1 Unit (Vitest, mocked Capacitor)

- `tarParser.test.ts` — feed minimal tar fixtures: single file, multi-file, directory, zero-byte file, large file (>512 byte), end-of-archive marker. Round-trip fixture generated by `tar -cf` in test setup.
- `decompressGzip.test.ts` — gzipped fixture → roundtrip equality. (Skipped if `DecompressionStream` not present in Node; fallback for Vitest environment via `zlib.gunzipSync` polyfill.)
- `repoExtractorService.test.ts` — mocked `Filesystem` + mocked `fetch`. Asserts: writes correct files, idempotent on second call, emits progress, fails gracefully on corrupt archive.
- `repoEditService.test.ts` — mocked filesystem + mocked isomorphic-git. Asserts: copies files Cache→Documents, calls git init/add/commit with expected args, persists SQLite row.
- `editableCodeService.test.ts` — write → diff shows the change → commit → diff empty → status correct.
- `capacitorFsAdapter.test.ts` — every fs method dispatches to the right Capacitor method with right args.

### 8.2 Integration (Vitest with real DecompressionStream when in node ≥ 18)

Generate a real tar.gz fixture (small, 5 files), feed through extractor with a Filesystem mock that captures writes. Assert all files extracted with right contents.

### 8.3 Manual matrix (Android device)

`doc/bundle_extract_test_matrix.md` — checklist:

- [ ] Cold app launch + open Code tool + view repo → progress shown, files appear within X s
- [ ] Re-open same repo → instant (Cache hit)
- [ ] Force-stop app, re-open same repo → still instant (Cache survives until OS evicts)
- [ ] Clear app cache from Android settings → next view re-extracts
- [ ] Edit a file in editable repo → diff shows hunks
- [ ] Commit edit → log shows new commit + diff empty
- [ ] resetFile → reverts that single file, others stay edited
- [ ] resetAll → all files revert to baseline, untracked deleted
- [ ] unpromote → editable copy gone, repo back to read-only Cache
- [ ] Reinstall app → editable repos persist (Documents survive); read-only Cache wiped

## 9. Performance Targets

| Operation | Target (mid-range Android device) |
|-----------|------------------------------------|
| `ensureExtracted` for typical 200-file repo | < 2 s |
| `ensureExtracted` for 1 500-file repo (whisper-cpp) | < 8 s |
| Re-extract (Cache hit) | < 50 ms |
| `promoteToEditable` for 200-file repo | < 5 s (Cache→Documents copy + git init/add/commit) |
| `git.diff` on a touched file | < 200 ms |
| `git.commit` of 1 file | < 500 ms |
| App startup overhead introduced | 0 ms (everything lazy) |

If targets are missed, revisit batching strategy and consider a native Capacitor plugin wrapping `libtar` + `zlib` (out of scope here).

## 10. Compatibility

- `DecompressionStream` is available in Android WebView since Chrome 80 (Feb 2020). Android 7 (API 24) WebView has been auto-updated past this version since 2020. We accept that very old, never-updated devices won't decompress; they'll see a clear error.
- `isomorphic-git` runs entirely in the WebView — no native code. Works on any Android version we already support.
- `tar` shell command is required at build time. Falls back to Node's `tar` package if absent (added to devDependencies as a safety net).

## 11. Roll-Out Plan

1. **Spec → plan → execute** in this branch (`develop_stream_deck_android` or fresh `develop_bundle_pipeline`).
2. After all tests pass, run a hardware build on an Android device, validate the manual matrix.
3. Commit migrations carefully: SQLite schema change is a `_v{N+1}` migration; any user with the previous build will run the new migration on first launch.
4. The first build with the new pipeline produces tar.gz files; on first launch with that build, no editable repos exist yet (that table starts empty), so users transparently get the new read-only flow.
5. Document the new manifest schema and the new services in `doc/SERVICES.md` and a new `doc/BUNDLE_PIPELINE.md`.

## 12. Open Questions

- **Cache eviction strategy**: when Android frees Cache and the user has unrelated repos extracted, do we eagerly re-extract on next launch or wait for first re-view? **Default**: lazy re-extract on view (no startup cost).
- **Concurrent extraction**: if the user navigates back and forth between repos quickly, do we serialize `ensureExtracted` calls per slug? **Default**: yes, in-flight promises cached per-slug to dedupe.
- **Build identifier**: how is `build_id` derived? **Default**: `git rev-parse --short HEAD || npm-version || mtime hash`. If git is unavailable at build time, falls back to package.json version + timestamp.
- **Conflicts after rebuild**: when the developer rebuilds and ships a new APK, an editable repo's baseline diverges from the new shipped baseline. **Default**: surface a "newer baseline available" warning in the UI; user choice to merge (manual) or stay on old baseline.
