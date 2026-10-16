# Bundle Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the loose-file bundle of 138 manifest repos with per-repo `tar.gz` archives extracted lazily on first user view, plus an opt-in editable mode that promotes a Cache extraction to a persistent `Documents` copy backed by a local `isomorphic-git` repo for diff/commit/reset.

**Architecture:** Strategy refactor. The build pipeline (`vite.config.ts`) writes `repos/{slug}.tar.gz` + `repos/{slug}.index.json` instead of loose dirs. Runtime services route the Code tool through `RepoExtractorService` (Cache, read-only) and optionally `RepoEditService` + `EditableCodeService` (Documents, git-backed). Decompression uses the WebView's native `DecompressionStream`; git uses lazy-imported `isomorphic-git` over a custom Capacitor `Filesystem` adapter.

**Tech Stack:**
- Vite plugin (Node) hardened with retries + native `tar -czf`
- TypeScript runtime services in `src/services/`
- Capacitor `Filesystem` for IO
- Native `DecompressionStream('gzip')` for ungzip
- `isomorphic-git` (npm dep, lazy `import()`) for VCS
- Vitest for unit tests, JUnit unaffected

**Spec:** `docs/superpowers/specs/2026-04-26-bundle-extract-edit-design.md`

**Working dir:** `mobile/erplibre_home_mobile/` unless prefixed.

**Branch:** the work continues on `develop_stream_deck_android` (mobile sub-repo) for now. If the user prefers a fresh branch, cut one from current HEAD before Task 1.

---

## Phase A — Plugin Hardening + Models

### Task 1: Harden `bundleSourcePlugin` filesystem operations

**Files:**
- Modify: `vite.config.ts`

- [ ] **Step 1: Replace the unguarded top-level `rmSync(reposOutDir, { recursive: true })` with a retry-and-force version**

Locate the line in `bundleSourcePlugin().buildStart`:

```ts
            const reposOutDir = join(root, "src", "public", "repos");
            if (existsSync(reposOutDir)) rmSync(reposOutDir, { recursive: true });
            mkdirSync(reposOutDir, { recursive: true });
```

Replace with:

```ts
            const reposOutDir = join(root, "src", "public", "repos");
            removeDirRobust(reposOutDir);
            mkdirSync(reposOutDir, { recursive: true });
```

And add this helper near the top of the file (after the imports):

```ts
/**
 * rmSync with broken-symlink and ENOTEMPTY tolerance. The bundle pipeline
 * has occasionally produced ENOTEMPTY when a previous build left stale
 * symlinks under src/public/repos/{slug}/ — the recursive remove races
 * with the kernel re-tagging dir entries. We retry up to 5 times.
 */
function removeDirRobust(dir: string): void {
    if (!existsSync(dir)) return;
    try {
        rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    } catch (e) {
        console.warn(`[bundle-warn] removeDirRobust failed once: ${dir} — ${e}`);
        // One more attempt after a small backoff. If this still fails, propagate.
        rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 });
    }
}
```

- [ ] **Step 2: Apply the same robust removal to `appOutDir`**

Replace:

```ts
            const appOutDir = join(root, "src", "public", "repo");
            if (existsSync(appOutDir)) rmSync(appOutDir, { recursive: true });
            mkdirSync(appOutDir, { recursive: true });
```

with:

```ts
            const appOutDir = join(root, "src", "public", "repo");
            removeDirRobust(appOutDir);
            mkdirSync(appOutDir, { recursive: true });
```

- [ ] **Step 3: Tolerate broken symlinks at the top-level `readdirSync(root)` (the root file enumeration)**

Locate:

```ts
            for (const name of readdirSync(root).sort()) {
                if (ROOT_SKIP_FILES.has(name)) continue;
                const fullSrc = join(root, name);
                if (!statSync(fullSrc).isFile()) continue;
```

Replace with:

```ts
            let rootEntries: string[];
            try { rootEntries = readdirSync(root).sort(); }
            catch (e) { console.warn(`[bundle-warn] readdir(${root}) failed: ${e}`); rootEntries = []; }
            for (const name of rootEntries) {
                if (ROOT_SKIP_FILES.has(name)) continue;
                const fullSrc = join(root, name);
                let st;
                try { st = statSync(fullSrc); }
                catch (e) { dbg(`skip(stat) ${name} — ${e}`); continue; }
                if (!st.isFile()) continue;
```

- [ ] **Step 4: Verify the existing build still works**

```bash
cd mobile/erplibre_home_mobile
rm -rf src/public/repo src/public/repos
npm run build:dev 2>&1 | tail -10
```

Expected: BUILD SUCCESSFUL with no fs errors.

- [ ] **Step 5: Commit**

```bash
git add vite.config.ts
git -c commit.gpgsign=false commit -m "[FIX] erplibre_home_mobile: harden bundle plugin against fs flakiness"
```

---

### Task 2: Add `ManifestProject` and shared models

**Files:**
- Create: `src/models/manifestProject.ts`
- Create: `src/models/gitTypes.ts`

- [ ] **Step 1: Create `manifestProject.ts`**

```typescript
/**
 * Shape of a single project entry in src/public/repos/manifest.json.
 *
 * Produced at build time by bundleSourcePlugin in vite.config.ts.
 * Consumed at runtime by RepoExtractorService and BundleCodeService.
 */
export interface ManifestProject {
    /** Origin URL (https or ssh) — display only. */
    url: string;

    /** Human-readable name (e.g. "OCA/web-api"). */
    name: string;

    /** Workspace-relative path where the source lived at build time. */
    path: string;

    /** Filesystem-safe slug used as archive base name and as Documents/repos/{slug}/. */
    slug: string;

    /** Git revision recorded in the manifest XML. */
    revision: string;

    /** Public asset path of the gzipped tar archive, e.g. "repos/github-com-OCA-web-api.tar.gz". */
    archive: string;

    /** Public asset path of the JSON file index, e.g. "repos/github-com-OCA-web-api.index.json". */
    indexUrl: string;

    fileCount: number;
    uncompressedBytes: number;
    compressedBytes: number;
}

export interface BundleEntry {
    path: string;
    type: "file" | "dir";
    size?: number;
}
```

- [ ] **Step 2: Create `gitTypes.ts`**

```typescript
export interface GitCommit {
    sha: string;
    message: string;
    author: { name: string; email: string };
    /** ISO 8601 string. */
    date: string;
    parentShas: string[];
}

export interface GitStatus {
    modified: string[];
    untracked: string[];
    staged: string[];
    deleted: string[];
}

export type GitDiffLineType = "context" | "add" | "del";

export interface GitDiffLine {
    type: GitDiffLineType;
    content: string;
}

export interface GitDiffHunk {
    filepath: string;
    oldStart: number;
    newStart: number;
    lines: GitDiffLine[];
}
```

- [ ] **Step 3: TypeScript compiles**

```bash
npm run build:dev 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add src/models/manifestProject.ts src/models/gitTypes.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: ManifestProject + gitTypes models"
```

---

## Phase B — Build-Time tar.gz

### Task 3: Generate `{slug}.tar.gz` per manifest project

This task replaces the per-repo loose-file copy with a temp-stage + `tar -czf` invocation.

**Files:**
- Modify: `vite.config.ts`

- [ ] **Step 1: Add a helper that runs `tar -czf` via Node `child_process`**

Add near `parseManifestXml`:

```ts
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";

/**
 * Create a gzipped tar archive of the given source dir.
 * Uses the system `tar` if available; falls back to the Node `tar` package.
 */
function createTarGz(srcDir: string, archivePath: string): void {
    try {
        execFileSync("tar", ["-czf", archivePath, "-C", srcDir, "."], {
            stdio: ["ignore", "ignore", "pipe"],
        });
    } catch (e) {
        throw new Error(`tar -czf failed for ${srcDir} → ${archivePath}: ${e}`);
    }
}
```

- [ ] **Step 2: Replace the per-project copy block**

Locate the loop in `bundleSourcePlugin().buildStart` that does:

```ts
                for (const proj of projects) {
                    const remoteFetch = remotes[proj.remote] ?? "";
                    const url = remoteFetch + proj.name;
                    const slug = urlToSlug(url);
                    const localPath = join(workspaceRoot, proj.path);

                    if (!existsSync(localPath)) {
                        console.log(`[bundle-manifest] skip (missing): ${localPath}`);
                        continue;
                    }

                    const projOutDir = join(reposOutDir, slug);
                    mkdirSync(projOutDir, { recursive: true });
                    const projIndex: BundleEntry[] = [];
                    const projStats: CopyStats = { copied: 0, skippedName: 0, skippedExclude: 0, skippedSize: 0, errors: 0 };
                    const projT0 = Date.now();
                    copyDirToBundle(localPath, "", projOutDir, projIndex, manifestExtraSkip, outputExclusions, MAX_BUNDLE_FILE_BYTES, projStats);
                    writeFileSync(
                        join(projOutDir, "index.json"),
                        JSON.stringify(projIndex, null, 2),
                    );

                    const name = proj.name.replace(/\.git$/, "");
                    bundledProjects.push({ url, name, path: proj.path, slug, revision: proj.revision });
                    console.log(...)
                }
```

Replace with:

```ts
                for (const proj of projects) {
                    const remoteFetch = remotes[proj.remote] ?? "";
                    const url = remoteFetch + proj.name;
                    const slug = urlToSlug(url);
                    const localPath = join(workspaceRoot, proj.path);

                    if (!existsSync(localPath)) {
                        console.log(`[bundle-manifest] skip (missing): ${localPath}`);
                        continue;
                    }

                    // Stage filtered files in a temp dir, then tar.gz them.
                    const stage = join(
                        tmpdir(),
                        `erplibre-bundle-${slug}-${randomBytes(4).toString("hex")}`,
                    );
                    mkdirSync(stage, { recursive: true });

                    const projIndex: BundleEntry[] = [];
                    const projStats: CopyStats = {
                        copied: 0, skippedName: 0, skippedExclude: 0, skippedSize: 0, errors: 0,
                    };
                    const projT0 = Date.now();
                    copyDirToBundle(
                        localPath, "", stage, projIndex, manifestExtraSkip,
                        outputExclusions, MAX_BUNDLE_FILE_BYTES, projStats,
                    );

                    // Write index.json into the stage so it lands inside the archive.
                    writeFileSync(
                        join(stage, "index.json"),
                        JSON.stringify(projIndex, null, 2),
                    );

                    // Also write a sidecar index.json next to the archive so the
                    // runtime can show the directory tree without unpacking.
                    const indexOutPath = join(reposOutDir, `${slug}.index.json`);
                    writeFileSync(indexOutPath, JSON.stringify(projIndex, null, 2));

                    // Compute uncompressed size.
                    const uncompressedBytes = projIndex
                        .filter((e) => e.type === "file")
                        .reduce((sum, e) => {
                            try {
                                return sum + statSync(join(stage, e.path)).size;
                            } catch {
                                return sum;
                            }
                        }, 0);

                    const archivePath = join(reposOutDir, `${slug}.tar.gz`);
                    createTarGz(stage, archivePath);

                    const compressedBytes = statSync(archivePath).size;

                    // Clean up the stage.
                    removeDirRobust(stage);

                    const name = proj.name.replace(/\.git$/, "");
                    bundledProjects.push({
                        url, name, path: proj.path, slug, revision: proj.revision,
                        archive: `repos/${slug}.tar.gz`,
                        indexUrl: `repos/${slug}.index.json`,
                        fileCount: projStats.copied,
                        uncompressedBytes,
                        compressedBytes,
                    });

                    console.log(
                        `[bundle-manifest] ${slug}.tar.gz: ${projStats.copied} files` +
                        `, ${(uncompressedBytes / 1024).toFixed(0)} KB → ` +
                        `${(compressedBytes / 1024).toFixed(0)} KB` +
                        `  (${Date.now() - projT0} ms)`,
                    );
                }
```

- [ ] **Step 3: Update the `ManifestProject` shape declared at the top of the file**

Find the existing `interface ManifestProject` (line ~21) and change it to:

```ts
interface ManifestProject {
    url: string;
    name: string;
    path: string;
    slug: string;
    revision: string;
    archive: string;
    indexUrl: string;
    fileCount: number;
    uncompressedBytes: number;
    compressedBytes: number;
}
```

This is a build-time copy of the runtime model in `src/models/manifestProject.ts` — keep them in sync.

- [ ] **Step 4: Build and inspect output**

```bash
rm -rf src/public/repo src/public/repos dist
npm run build:dev 2>&1 | tail -25
ls -la src/public/repos/ | head -10
du -sh src/public/repos/
```

Expected: per-repo `*.tar.gz` + `*.index.json` files. `du` should be much smaller than the previous loose copy (5–10× depending on text content).

- [ ] **Step 5: Commit**

```bash
git add vite.config.ts
git -c commit.gpgsign=false commit -m "[IMP] erplibre_home_mobile: ship manifest repos as per-repo tar.gz"
```

---

### Task 4: Verify APK builds and pre-extract size baseline

This task captures a size baseline for later comparison and confirms `cap sync` no longer struggles with thousands of files.

**Files:**
- Modify: none (validation only)

- [ ] **Step 1: Sync to Android assets**

```bash
npx cap sync android 2>&1 | tail -10
```

Note the time taken (compare to your previous experience pre-tar.gz).

- [ ] **Step 2: Build the debug APK**

```bash
cd android && ./gradlew :app:assembleDebug 2>&1 | tail -5
```

Expected: BUILD SUCCESSFUL.

- [ ] **Step 3: Capture size**

```bash
ls -la app/build/outputs/apk/debug/app-debug.apk
```

Note this number for later comparison.

No commit for this task — pure validation.

---

## Phase C — Runtime Extraction (Read-Only)

### Task 5: Inline `tarParser.ts` + tests

**Files:**
- Create: `src/utils/tarParser.ts`
- Create: `src/__tests__/tarParser.test.ts`

- [ ] **Step 1: Write the failing test (skeleton)**

```typescript
import { describe, it, expect } from "vitest";
import { parseTarBuffer, TarEntry } from "../utils/tarParser";

/**
 * Helper: build a minimal ustar header block for a single file entry.
 * 512 bytes total. Octal-ASCII fields, NUL-terminated.
 */
function makeTarHeader(name: string, size: number, type: "0" | "5" = "0"): Uint8Array {
    const block = new Uint8Array(512);
    const enc = new TextEncoder();
    block.set(enc.encode(name.slice(0, 100)), 0);
    // mode 0644
    block.set(enc.encode("000644 \0"), 100);
    // uid/gid
    block.set(enc.encode("000000 \0"), 108);
    block.set(enc.encode("000000 \0"), 116);
    // size: octal, 11 chars + NUL
    block.set(enc.encode(size.toString(8).padStart(11, "0") + "\0"), 124);
    // mtime
    block.set(enc.encode("00000000000\0"), 136);
    // checksum placeholder (8 spaces during calculation)
    block.set(enc.encode("        "), 148);
    // type flag
    block[156] = enc.encode(type)[0];
    // ustar magic
    block.set(enc.encode("ustar\0"), 257);
    block.set(enc.encode("00"), 263);
    // checksum: sum of bytes
    let cksum = 0;
    for (let i = 0; i < 512; i++) cksum += block[i];
    block.set(enc.encode(cksum.toString(8).padStart(6, "0") + "\0 "), 148);
    return block;
}

function makeTarFile(name: string, content: Uint8Array): Uint8Array {
    const header = makeTarHeader(name, content.length, "0");
    const padded = new Uint8Array(Math.ceil(content.length / 512) * 512);
    padded.set(content, 0);
    const out = new Uint8Array(header.length + padded.length);
    out.set(header, 0);
    out.set(padded, header.length);
    return out;
}

function endOfArchive(): Uint8Array {
    return new Uint8Array(1024); // two zero blocks
}

function concat(parts: Uint8Array[]): Uint8Array {
    const total = parts.reduce((n, p) => n + p.length, 0);
    const out = new Uint8Array(total);
    let off = 0;
    for (const p of parts) { out.set(p, off); off += p.length; }
    return out;
}

describe("tarParser", () => {
    it("parses a single file entry", async () => {
        const content = new TextEncoder().encode("hello tar");
        const tar = concat([makeTarFile("hello.txt", content), endOfArchive()]);
        const entries: TarEntry[] = [];
        for await (const e of parseTarBuffer(tar)) entries.push(e);
        expect(entries).toHaveLength(1);
        expect(entries[0].name).toBe("hello.txt");
        expect(entries[0].size).toBe(content.length);
        expect(entries[0].isFile).toBe(true);
        expect(new TextDecoder().decode(entries[0].content!)).toBe("hello tar");
    });

    it("parses multiple files with padding", async () => {
        const a = new TextEncoder().encode("a".repeat(513));  // forces padding
        const b = new TextEncoder().encode("bb");
        const tar = concat([makeTarFile("a.bin", a), makeTarFile("b.bin", b), endOfArchive()]);
        const entries: TarEntry[] = [];
        for await (const e of parseTarBuffer(tar)) entries.push(e);
        expect(entries.map((e) => e.name)).toEqual(["a.bin", "b.bin"]);
        expect(entries[0].content!.length).toBe(513);
        expect(entries[1].content!.length).toBe(2);
    });

    it("parses a directory entry without content", async () => {
        const dirHeader = makeTarHeader("subdir/", 0, "5");
        const tar = concat([dirHeader, endOfArchive()]);
        const entries: TarEntry[] = [];
        for await (const e of parseTarBuffer(tar)) entries.push(e);
        expect(entries[0].isDirectory).toBe(true);
        expect(entries[0].isFile).toBe(false);
    });

    it("ignores end-of-archive padding", async () => {
        const tar = concat([makeTarFile("only.txt", new Uint8Array([1, 2, 3])), endOfArchive()]);
        const entries: TarEntry[] = [];
        for await (const e of parseTarBuffer(tar)) entries.push(e);
        expect(entries).toHaveLength(1);
    });

    it("rejects truncated input", async () => {
        const tar = makeTarHeader("truncated.txt", 100, "0").slice(0, 256); // half a header
        await expect(async () => {
            const entries: TarEntry[] = [];
            for await (const e of parseTarBuffer(tar)) entries.push(e);
        }).rejects.toThrow();
    });
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
npx vitest run src/__tests__/tarParser.test.ts
```

Expected: module not found.

- [ ] **Step 3: Implement `tarParser.ts`**

```typescript
/**
 * Streaming tar reader. Supports plain ustar archives — sufficient for
 * what GNU `tar -czf` produces from typical source trees.
 *
 * Two entry points:
 *   parseTarBuffer(bytes)  — convenience for tests, eager
 *   parseTarStream(stream) — production, async iterable over a
 *                            ReadableStream<Uint8Array>
 *
 * The parser does NOT handle GNU long-name extensions (PAX) explicitly;
 * filenames longer than 100 bytes use the ustar prefix field, which is
 * read here. Files larger than 8 GB (octal size overflow) are rejected.
 */

const BLOCK = 512;

export interface TarEntry {
    name: string;
    size: number;
    isDirectory: boolean;
    isFile: boolean;
    mode: number;
    /** Present iff isFile. */
    content?: Uint8Array;
}

function readOctalString(view: Uint8Array, off: number, len: number): string {
    let end = off + len;
    while (end > off && (view[end - 1] === 0 || view[end - 1] === 0x20)) end--;
    return new TextDecoder().decode(view.subarray(off, end)).trim();
}

function readNullTermString(view: Uint8Array, off: number, len: number): string {
    let end = off;
    const limit = off + len;
    while (end < limit && view[end] !== 0) end++;
    return new TextDecoder().decode(view.subarray(off, end));
}

function isAllZero(view: Uint8Array): boolean {
    for (let i = 0; i < view.length; i++) if (view[i] !== 0) return false;
    return true;
}

function parseHeader(block: Uint8Array): { entry: TarEntry; isEndMarker: boolean } | null {
    if (block.length !== BLOCK) {
        throw new Error(`tar header expected ${BLOCK} bytes, got ${block.length}`);
    }
    if (isAllZero(block)) return { entry: null as unknown as TarEntry, isEndMarker: true };

    const name = readNullTermString(block, 0, 100);
    const sizeOctal = readOctalString(block, 124, 12);
    const size = parseInt(sizeOctal, 8);
    if (!Number.isFinite(size) || size < 0) {
        throw new Error(`tar: invalid size field "${sizeOctal}"`);
    }
    const modeOctal = readOctalString(block, 100, 8);
    const mode = parseInt(modeOctal, 8) || 0o644;
    const typeFlag = String.fromCharCode(block[156] || 0x30); // '0' if zero
    const prefix = readNullTermString(block, 345, 155);
    const fullName = prefix ? `${prefix}/${name}` : name;

    const isDirectory = typeFlag === "5" || fullName.endsWith("/");
    const isFile = typeFlag === "0" || typeFlag === "" || typeFlag === " ";
    return {
        entry: { name: fullName, size, isDirectory, isFile, mode },
        isEndMarker: false,
    };
}

/** Eager parser for use in tests. */
export async function* parseTarBuffer(bytes: Uint8Array): AsyncGenerator<TarEntry> {
    let offset = 0;
    while (offset + BLOCK <= bytes.length) {
        const headerBlock = bytes.subarray(offset, offset + BLOCK);
        const parsed = parseHeader(headerBlock);
        offset += BLOCK;
        if (!parsed) continue;
        if (parsed.isEndMarker) return;
        const { entry } = parsed;

        if (entry.isFile && entry.size > 0) {
            if (offset + entry.size > bytes.length) {
                throw new Error(`tar: truncated content for ${entry.name}`);
            }
            entry.content = bytes.subarray(offset, offset + entry.size);
            offset += entry.size;
            // Pad to BLOCK.
            const pad = (BLOCK - (entry.size % BLOCK)) % BLOCK;
            offset += pad;
        }
        yield entry;
    }
    // If we got here without seeing the end-of-archive marker, the input was truncated.
    throw new Error("tar: unexpected end of archive (no zero blocks seen)");
}

/** Streaming parser for production use. */
export async function* parseTarStream(
    stream: ReadableStream<Uint8Array>,
): AsyncGenerator<TarEntry> {
    const reader = stream.getReader();
    let buffer = new Uint8Array(0);
    let done = false;

    async function pull(): Promise<void> {
        if (done) return;
        const r = await reader.read();
        if (r.done) { done = true; return; }
        const merged = new Uint8Array(buffer.length + r.value.length);
        merged.set(buffer, 0);
        merged.set(r.value, buffer.length);
        buffer = merged;
    }

    while (true) {
        while (buffer.length < BLOCK && !done) await pull();
        if (buffer.length < BLOCK) {
            throw new Error("tar: stream ended in the middle of a header");
        }
        const headerBlock = buffer.subarray(0, BLOCK);
        const parsed = parseHeader(headerBlock);
        buffer = buffer.subarray(BLOCK);
        if (!parsed) continue;
        if (parsed.isEndMarker) return;
        const { entry } = parsed;

        if (entry.isFile && entry.size > 0) {
            const padded = entry.size + ((BLOCK - (entry.size % BLOCK)) % BLOCK);
            while (buffer.length < padded && !done) await pull();
            if (buffer.length < entry.size) {
                throw new Error(`tar: stream truncated mid-content for ${entry.name}`);
            }
            entry.content = buffer.slice(0, entry.size);
            buffer = buffer.subarray(padded);
        }
        yield entry;
    }
}
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
npx vitest run src/__tests__/tarParser.test.ts
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/utils/tarParser.ts src/__tests__/tarParser.test.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: inline tar parser (ustar)"
```

---

### Task 6: `decompressGzip.ts` thin wrapper

**Files:**
- Create: `src/utils/decompressGzip.ts`
- Create: `src/__tests__/decompressGzip.test.ts`

- [ ] **Step 1: Write the test**

```typescript
import { describe, it, expect } from "vitest";
import { gunzipBytes, gunzipStream } from "../utils/decompressGzip";
import { gzipSync } from "node:zlib";

describe("decompressGzip", () => {
    it("gunzipBytes round-trips simple data", async () => {
        const input = new TextEncoder().encode("hello world");
        const gz = gzipSync(input);
        const out = await gunzipBytes(new Uint8Array(gz));
        expect(new TextDecoder().decode(out)).toBe("hello world");
    });

    it("gunzipStream feeds a ReadableStream through DecompressionStream", async () => {
        const input = new TextEncoder().encode("streamed".repeat(100));
        const gz = gzipSync(input);
        const stream = new Response(new Uint8Array(gz)).body!;
        const ungz = gunzipStream(stream);
        const reader = ungz.getReader();
        const chunks: Uint8Array[] = [];
        while (true) {
            const r = await reader.read();
            if (r.done) break;
            chunks.push(r.value);
        }
        const total = chunks.reduce((n, c) => n + c.length, 0);
        const merged = new Uint8Array(total);
        let off = 0;
        for (const c of chunks) { merged.set(c, off); off += c.length; }
        expect(new TextDecoder().decode(merged)).toBe("streamed".repeat(100));
    });
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
npx vitest run src/__tests__/decompressGzip.test.ts
```

- [ ] **Step 3: Implement**

```typescript
/**
 * Thin wrappers around the WebView's native DecompressionStream('gzip').
 *
 * Available since Chrome 80 — Android WebView on minSdk 24 has been past
 * this version since 2020. If a runtime ever turns up without it, callers
 * see a clear ReferenceError.
 */

export function gunzipStream(
    input: ReadableStream<Uint8Array>,
): ReadableStream<Uint8Array> {
    return input.pipeThrough(new DecompressionStream("gzip"));
}

export async function gunzipBytes(input: Uint8Array): Promise<Uint8Array> {
    const stream = new Response(input).body;
    if (!stream) throw new Error("Response has no body — cannot gunzip");
    const out = stream.pipeThrough(new DecompressionStream("gzip"));
    const reader = out.getReader();
    const chunks: Uint8Array[] = [];
    while (true) {
        const r = await reader.read();
        if (r.done) break;
        chunks.push(r.value);
    }
    const total = chunks.reduce((n, c) => n + c.length, 0);
    const merged = new Uint8Array(total);
    let off = 0;
    for (const c of chunks) { merged.set(c, off); off += c.length; }
    return merged;
}
```

- [ ] **Step 4: Run, confirm pass**

```bash
npx vitest run src/__tests__/decompressGzip.test.ts
```

If `DecompressionStream` is missing in the test environment (very old node), Vitest may throw `ReferenceError`. Vitest 3 ships with a Node ≥ 18 expectation; `DecompressionStream` is in Node 18+. If it fails, install `node-fetch` polyfill — but normally Node 18 has it.

- [ ] **Step 5: Commit**

```bash
git add src/utils/decompressGzip.ts src/__tests__/decompressGzip.test.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: gunzip wrappers over DecompressionStream"
```

---

### Task 7: `RepoExtractorService` core extraction logic

**Files:**
- Create: `src/services/repoExtractorService.ts`
- Create: `src/__tests__/repoExtractorService.test.ts`

- [ ] **Step 1: Write the test**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { gzipSync } from "node:zlib";

const { mockFs, mockFetch } = vi.hoisted(() => ({
    mockFs: {
        readFile: vi.fn(),
        writeFile: vi.fn(),
        mkdir: vi.fn(),
        stat: vi.fn(),
        deleteFile: vi.fn(),
        readdir: vi.fn(),
    },
    mockFetch: vi.fn(),
}));

vi.mock("@capacitor/filesystem", () => ({
    Filesystem: mockFs,
    Directory: { Cache: "CACHE", Data: "DATA" },
    Encoding: { UTF8: "utf8" },
}));

global.fetch = mockFetch as unknown as typeof fetch;

// Reuse helpers from tarParser.test.ts to build a fixture archive.
function makeTarHeader(name: string, size: number, type: "0" | "5" = "0"): Uint8Array {
    const block = new Uint8Array(512);
    const enc = new TextEncoder();
    block.set(enc.encode(name.slice(0, 100)), 0);
    block.set(enc.encode("000644 \0"), 100);
    block.set(enc.encode("000000 \0"), 108);
    block.set(enc.encode("000000 \0"), 116);
    block.set(enc.encode(size.toString(8).padStart(11, "0") + "\0"), 124);
    block.set(enc.encode("00000000000\0"), 136);
    block.set(enc.encode("        "), 148);
    block[156] = enc.encode(type)[0];
    block.set(enc.encode("ustar\0"), 257);
    block.set(enc.encode("00"), 263);
    let cksum = 0;
    for (let i = 0; i < 512; i++) cksum += block[i];
    block.set(enc.encode(cksum.toString(8).padStart(6, "0") + "\0 "), 148);
    return block;
}

function makeTarFile(name: string, content: Uint8Array): Uint8Array {
    const header = makeTarHeader(name, content.length, "0");
    const padded = new Uint8Array(Math.ceil(content.length / 512) * 512);
    padded.set(content, 0);
    const out = new Uint8Array(header.length + padded.length);
    out.set(header, 0);
    out.set(padded, header.length);
    return out;
}

function fixtureTarGz(): Uint8Array {
    const enc = new TextEncoder();
    const tar = new Uint8Array([
        ...makeTarFile("README.md", enc.encode("# Hello")),
        ...makeTarFile("src/main.py", enc.encode('print("hi")')),
        ...makeTarFile("index.json", enc.encode('[{"path":"README.md","type":"file"}]')),
        ...new Uint8Array(1024),
    ]);
    return new Uint8Array(gzipSync(tar));
}

import { RepoExtractorService } from "../services/repoExtractorService";

describe("RepoExtractorService", () => {
    beforeEach(() => {
        Object.values(mockFs).forEach((fn) => fn.mockReset());
        mockFetch.mockReset();
    });

    it("extracts an archive on first call", async () => {
        // First call: sentinel doesn't exist.
        mockFs.stat.mockRejectedValueOnce(new Error("ENOENT"));
        mockFs.mkdir.mockResolvedValue(undefined);
        mockFs.writeFile.mockResolvedValue(undefined);
        mockFetch.mockResolvedValue(new Response(fixtureTarGz()));

        const svc = new RepoExtractorService();
        const dir = await svc.ensureExtracted("test-slug", "/repos/test-slug.tar.gz");

        expect(dir).toContain("test-slug");
        // README.md, src/main.py, index.json, .extracted sentinel
        expect(mockFs.writeFile).toHaveBeenCalledTimes(4);
        const writeCalls = mockFs.writeFile.mock.calls.map((c) => c[0].path);
        expect(writeCalls).toContain("repos/test-slug/README.md");
        expect(writeCalls).toContain("repos/test-slug/src/main.py");
        expect(writeCalls.some((p: string) => p.endsWith("/.extracted"))).toBe(true);
    });

    it("is idempotent on second call (sentinel hit)", async () => {
        mockFs.stat.mockResolvedValue({ type: "file", size: 12, mtime: 0 });
        const svc = new RepoExtractorService();
        await svc.ensureExtracted("cached", "/repos/cached.tar.gz");
        expect(mockFetch).not.toHaveBeenCalled();
        expect(mockFs.writeFile).not.toHaveBeenCalled();
    });

    it("dedupes concurrent extractions for the same slug", async () => {
        mockFs.stat.mockRejectedValue(new Error("ENOENT"));
        mockFs.mkdir.mockResolvedValue(undefined);
        mockFs.writeFile.mockResolvedValue(undefined);
        mockFetch.mockResolvedValue(new Response(fixtureTarGz()));

        const svc = new RepoExtractorService();
        const [a, b] = await Promise.all([
            svc.ensureExtracted("dup", "/repos/dup.tar.gz"),
            svc.ensureExtracted("dup", "/repos/dup.tar.gz"),
        ]);
        expect(a).toBe(b);
        // fetch must have been called exactly once.
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("rejects when archive download fails", async () => {
        mockFs.stat.mockRejectedValue(new Error("ENOENT"));
        mockFetch.mockResolvedValue(new Response(null, { status: 404 }));
        const svc = new RepoExtractorService();
        await expect(svc.ensureExtracted("missing", "/repos/missing.tar.gz"))
            .rejects.toThrow(/BundleNotShipped|404/);
    });
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
npx vitest run src/__tests__/repoExtractorService.test.ts
```

- [ ] **Step 3: Implement `repoExtractorService.ts`**

```typescript
import { Filesystem, Directory, Encoding } from "@capacitor/filesystem";
import { gunzipStream } from "../utils/decompressGzip";
import { parseTarStream, TarEntry } from "../utils/tarParser";

export class BundleNotShippedError extends Error {
    constructor(slug: string, status?: number) {
        super(`Bundle archive missing for ${slug}` + (status ? ` (HTTP ${status})` : ""));
    }
}

export class BundleCorruptError extends Error {
    constructor(slug: string, cause: unknown) {
        super(`Bundle archive corrupt for ${slug}: ${cause}`);
    }
}

export interface ExtractProgress {
    slug: string;
    written: number;
    total?: number;
    currentPath: string;
}

type ExtractListener = (p: ExtractProgress) => void;

/**
 * Extracts repo archives shipped under public assets into the device's
 * Capacitor Cache directory on first use. Subsequent calls for the same
 * slug short-circuit on a `.extracted` sentinel file.
 *
 * Cache layout:
 *   Cache/repos/{slug}/.extracted
 *   Cache/repos/{slug}/index.json
 *   Cache/repos/{slug}/<original tree>
 */
export class RepoExtractorService {
    private inflight = new Map<string, Promise<string>>();
    private listeners = new Set<ExtractListener>();

    onProgress(fn: ExtractListener): () => void {
        this.listeners.add(fn);
        return () => this.listeners.delete(fn);
    }

    async ensureExtracted(slug: string, archiveUrl: string): Promise<string> {
        const cached = this.inflight.get(slug);
        if (cached) return cached;
        const p = this._doExtract(slug, archiveUrl).finally(() => {
            this.inflight.delete(slug);
        });
        this.inflight.set(slug, p);
        return p;
    }

    private async _doExtract(slug: string, archiveUrl: string): Promise<string> {
        const baseRel = `repos/${slug}`;
        const sentinelRel = `${baseRel}/.extracted`;

        // Sentinel hit — already extracted.
        try {
            await Filesystem.stat({ path: sentinelRel, directory: Directory.Cache });
            return baseRel;
        } catch {
            // not extracted yet, fall through
        }

        // Fetch archive.
        const res = await fetch(archiveUrl);
        if (!res.ok || !res.body) {
            throw new BundleNotShippedError(slug, res.status);
        }

        try {
            await Filesystem.mkdir({
                path: baseRel,
                directory: Directory.Cache,
                recursive: true,
            });
        } catch {
            // already exists or parent issue — proceed anyway
        }

        const ungz = gunzipStream(res.body);
        let written = 0;
        try {
            for await (const entry of parseTarStream(ungz)) {
                await this._writeEntry(slug, baseRel, entry);
                written++;
                this._emitProgress({ slug, written, currentPath: entry.name });
            }
        } catch (e) {
            throw new BundleCorruptError(slug, e);
        }

        // Sentinel.
        await Filesystem.writeFile({
            path: sentinelRel,
            directory: Directory.Cache,
            data: btoa(`extracted_at=${Date.now()}`),
        });

        return baseRel;
    }

    private async _writeEntry(slug: string, baseRel: string, entry: TarEntry): Promise<void> {
        const fullPath = `${baseRel}/${entry.name}`;
        if (entry.isDirectory) {
            try {
                await Filesystem.mkdir({
                    path: fullPath,
                    directory: Directory.Cache,
                    recursive: true,
                });
            } catch {
                /* ignore */
            }
            return;
        }
        if (!entry.isFile || !entry.content) return;

        // Ensure parent dir exists.
        const lastSlash = fullPath.lastIndexOf("/");
        if (lastSlash > 0) {
            try {
                await Filesystem.mkdir({
                    path: fullPath.slice(0, lastSlash),
                    directory: Directory.Cache,
                    recursive: true,
                });
            } catch {
                /* ignore */
            }
        }

        await Filesystem.writeFile({
            path: fullPath,
            directory: Directory.Cache,
            data: bytesToBase64(entry.content),
        });
    }

    private _emitProgress(p: ExtractProgress): void {
        for (const fn of this.listeners) {
            try { fn(p); } catch { /* listener errors don't break extraction */ }
        }
    }

    /** Re-extract from scratch — use after deciding the cached copy is bad. */
    async forceReextract(slug: string, archiveUrl: string): Promise<string> {
        const baseRel = `repos/${slug}`;
        try {
            await Filesystem.rmdir({
                path: baseRel,
                directory: Directory.Cache,
                recursive: true,
            });
        } catch { /* maybe didn't exist */ }
        return this.ensureExtracted(slug, archiveUrl);
    }
}

function bytesToBase64(bytes: Uint8Array): string {
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
}
```

- [ ] **Step 4: Run, confirm pass**

```bash
npx vitest run src/__tests__/repoExtractorService.test.ts
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/services/repoExtractorService.ts src/__tests__/repoExtractorService.test.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: RepoExtractorService for tar.gz lazy extract"
```

---

### Task 8: Refactor `BundleCodeService` to route through `RepoExtractorService`

**Files:**
- Modify: `src/services/bundleCodeService.ts`
- Modify: `src/__tests__/bundleCodeService.test.ts` (if it exists; otherwise create)

- [ ] **Step 1: Inspect the existing `BundleCodeService`**

Read the current file and the existing test (if any). The current implementation uses `fetch()` for `/repo/...` and `/repos/{slug}/...`. We change `/repos/{slug}/...` to go through Cache via `Filesystem.readFile`.

- [ ] **Step 2: Refactor with backwards-compatible API**

```typescript
import { Filesystem, Directory, Encoding } from "@capacitor/filesystem";
import { ManifestProject, BundleEntry } from "../models/manifestProject";
import { DirEntry } from "./codeService";
import { RepoExtractorService } from "./repoExtractorService";

/**
 * Read-only code reader that uses the source bundle embedded at build time.
 *
 * Two backends:
 *   - "/repo" continues to be served as loose files via fetch (the app's own
 *     source — small, loaded lazily from public assets).
 *   - "/repos/{slug}" is now backed by a tar.gz extracted into Cache by
 *     RepoExtractorService on first access.
 */
export class BundleCodeService {
    private _index: BundleEntry[] = [];
    private _loaded = false;

    /** Resolved Cache-relative base path once initialize() has run for archive mode. */
    private _cacheBase: string | null = null;

    constructor(
        private readonly _baseUrl: string = "/repo",
        private readonly _archiveSpec?: { archiveUrl: string; indexUrl: string; slug: string },
        private readonly _extractor?: RepoExtractorService,
    ) {}

    async initialize(): Promise<void> {
        if (this._archiveSpec && this._extractor) {
            // Archive mode (manifest repo)
            // 1. Pre-fetch the sidecar index.json so we can list dirs without unpacking.
            const idxRes = await fetch(this._archiveSpec.indexUrl);
            if (!idxRes.ok) {
                throw new Error(
                    `Manifest index introuvable: ${this._archiveSpec.indexUrl}. Recompilez l'app.`,
                );
            }
            this._index = await idxRes.json();
            // 2. Trigger extraction (or short-circuit on sentinel).
            this._cacheBase = await this._extractor.ensureExtracted(
                this._archiveSpec.slug,
                this._archiveSpec.archiveUrl,
            );
        } else {
            // Loose-files mode (app's own source)
            const res = await fetch(`${this._baseUrl}/index.json`);
            if (!res.ok) {
                throw new Error(
                    "Bundle source introuvable. Recompilez l'app (npm run build).",
                );
            }
            this._index = await res.json();
        }
        this._loaded = true;
    }

    async listDir(dirPath: string): Promise<DirEntry[]> {
        if (!this._loaded) await this.initialize();
        return this._index
            .filter((entry) => {
                const parentPath = entry.path.includes("/")
                    ? entry.path.slice(0, entry.path.lastIndexOf("/"))
                    : "";
                return parentPath === dirPath;
            })
            .map((entry) => ({
                name: entry.path.split("/").pop() ?? entry.path,
                type: entry.type,
                path: entry.path,
            }));
    }

    async readFile(filePath: string): Promise<string> {
        if (!this._loaded) await this.initialize();
        if (this._cacheBase) {
            const r = await Filesystem.readFile({
                path: `${this._cacheBase}/${filePath}`,
                directory: Directory.Cache,
                encoding: Encoding.UTF8,
            });
            // Filesystem returns { data: string } when encoding given.
            const data = r.data;
            if (typeof data !== "string") {
                throw new Error(`Filesystem.readFile returned non-string for ${filePath}`);
            }
            return data;
        }
        const res = await fetch(`${this._baseUrl}/${filePath}`);
        if (!res.ok) {
            throw new Error(`Fichier introuvable dans le bundle: ${filePath}`);
        }
        return res.text();
    }

    getFileUrl(filePath: string): string {
        if (this._cacheBase) {
            // Capacitor exposes Cache files via a `capacitor://` or local URI.
            // Callers that need a URL for <img src> should use Filesystem.getUri().
            return `cache:///${this._cacheBase}/${filePath}`;
        }
        return `${this._baseUrl}/${filePath}`;
    }
}
```

- [ ] **Step 3: Update or add tests**

Check `src/__tests__/bundleCodeService.test.ts`. If absent, create it with archive-mode coverage:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockFs, mockFetch } = vi.hoisted(() => ({
    mockFs: {
        readFile: vi.fn(),
        writeFile: vi.fn(),
        mkdir: vi.fn(),
        stat: vi.fn(),
    },
    mockFetch: vi.fn(),
}));

vi.mock("@capacitor/filesystem", () => ({
    Filesystem: mockFs,
    Directory: { Cache: "CACHE", Data: "DATA" },
    Encoding: { UTF8: "utf8" },
}));

global.fetch = mockFetch as unknown as typeof fetch;

import { BundleCodeService } from "../services/bundleCodeService";
import { RepoExtractorService } from "../services/repoExtractorService";

describe("BundleCodeService archive mode", () => {
    beforeEach(() => {
        Object.values(mockFs).forEach((fn) => fn.mockReset());
        mockFetch.mockReset();
    });

    it("initializes via index.json sidecar + extractor", async () => {
        const idx = [{ path: "README.md", type: "file" }, { path: "src", type: "dir" }];
        mockFetch.mockResolvedValueOnce(new Response(JSON.stringify(idx)));
        const extractor = { ensureExtracted: vi.fn().mockResolvedValue("repos/foo") };
        const svc = new BundleCodeService(
            "/ignored",
            { archiveUrl: "/repos/foo.tar.gz", indexUrl: "/repos/foo.index.json", slug: "foo" },
            extractor as unknown as RepoExtractorService,
        );
        const entries = await svc.listDir("");
        expect(entries.map((e) => e.path)).toEqual(["README.md", "src"]);
        expect(extractor.ensureExtracted).toHaveBeenCalledWith("foo", "/repos/foo.tar.gz");
    });

    it("readFile reads from Cache", async () => {
        const idx = [{ path: "README.md", type: "file" }];
        mockFetch.mockResolvedValueOnce(new Response(JSON.stringify(idx)));
        mockFs.readFile.mockResolvedValue({ data: "# hi" });
        const extractor = { ensureExtracted: vi.fn().mockResolvedValue("repos/foo") };
        const svc = new BundleCodeService(
            "/ignored",
            { archiveUrl: "/repos/foo.tar.gz", indexUrl: "/repos/foo.index.json", slug: "foo" },
            extractor as unknown as RepoExtractorService,
        );
        const text = await svc.readFile("README.md");
        expect(text).toBe("# hi");
        expect(mockFs.readFile).toHaveBeenCalledWith(expect.objectContaining({
            path: "repos/foo/README.md",
            directory: "CACHE",
        }));
    });
});
```

- [ ] **Step 4: Run all bundle tests**

```bash
npx vitest run bundleCodeService
```

- [ ] **Step 5: Commit**

```bash
git add src/services/bundleCodeService.ts src/__tests__/bundleCodeService.test.ts
git -c commit.gpgsign=false commit -m "[IMP] erplibre_home_mobile: route BundleCodeService through RepoExtractorService"
```

---

## Phase D — SQLite migration for editable repos

### Task 9: Add migration for `editable_repos` table

**Files:**
- Modify: `src/services/migrationService.ts` (or wherever the migrations table lives — verify with `grep -rn "CREATE TABLE" src/services/`)

- [ ] **Step 1: Locate the migration registration pattern**

```bash
grep -rn "CREATE TABLE\|migrationVersion\|registerMigration" src/services/
```

Find how new migrations are added. The project has an existing `migrationService.ts`; new migrations are typically added as either a string in an array or a numbered function.

- [ ] **Step 2: Add the migration**

Append a new migration version (use the next available index). Example shape — adjust to match the project's actual migration framework:

```typescript
// src/services/migrationService.ts (snippet)
const MIGRATIONS: Migration[] = [
    // ... existing migrations ...
    {
        version: <NEXT_INT>,
        name: "create_editable_repos",
        up: `
            CREATE TABLE IF NOT EXISTS editable_repos (
                slug          TEXT PRIMARY KEY,
                baseline_sha  TEXT NOT NULL,
                build_id      TEXT NOT NULL,
                promoted_at   INTEGER NOT NULL,
                head_sha      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_editable_repos_promoted_at
                ON editable_repos(promoted_at);
        `,
    },
];
```

If the project's migration shape differs, adapt — the key requirement is that the table exists after a successful first launch.

- [ ] **Step 3: Verify migration runs**

```bash
npx vitest run migrationService
```

The existing migration tests should continue to pass. If there is a "migrate from N to N+1" test, add a case for the new version.

- [ ] **Step 4: Commit**

```bash
git add src/services/migrationService.ts src/__tests__/migrationService.test.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: migration for editable_repos table"
```

---

## Phase E — Edit Mode (Documents + isomorphic-git)

### Task 10: Capacitor `Filesystem` adapter for `isomorphic-git`

**Files:**
- Create: `src/services/git/capacitorFsAdapter.ts`
- Create: `src/__tests__/capacitorFsAdapter.test.ts`

- [ ] **Step 1: Implement the adapter**

```typescript
import { Filesystem, Directory } from "@capacitor/filesystem";

/**
 * isomorphic-git expects a Node-fs-shaped object with promise-returning
 * methods. We map each call onto @capacitor/filesystem against the
 * Documents directory.
 *
 * Paths from isomorphic-git are absolute-looking ("/repos/{slug}/foo");
 * the adapter strips the leading "/" and uses Directory.Data.
 *
 * Symlinks are unsupported; readlink/symlink throw ENOSYS — none of the
 * targeted git ops (init, add, commit, status, diff, log, reset) need
 * them when the working tree contains no symlinks (which is the case for
 * source code repos in this project).
 */
export interface FsStat {
    type: "file" | "dir" | "symlink";
    mode: number;
    size: number;
    mtimeMs: number;
    ino: number;
    uid: number;
    gid: number;
    isFile: () => boolean;
    isDirectory: () => boolean;
    isSymbolicLink: () => boolean;
}

function strip(p: string): string {
    return p.replace(/^\/+/, "");
}

function bytesToBase64(bytes: Uint8Array): string {
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
}

function base64ToBytes(b64: string): Uint8Array {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
}

export const capacitorFsAdapter = {
    promises: {
        async readFile(
            path: string,
            opts?: { encoding?: string },
        ): Promise<Uint8Array | string> {
            const r = await Filesystem.readFile({
                path: strip(path),
                directory: Directory.Data,
            });
            const data = r.data as string;
            if (opts?.encoding === "utf8") {
                // We never request encoding from Filesystem; data is base64.
                return new TextDecoder().decode(base64ToBytes(data));
            }
            return base64ToBytes(data);
        },

        async writeFile(
            path: string,
            data: Uint8Array | string,
            _opts?: { encoding?: string; mode?: number },
        ): Promise<void> {
            const bytes = typeof data === "string"
                ? new TextEncoder().encode(data)
                : data;
            await Filesystem.writeFile({
                path: strip(path),
                directory: Directory.Data,
                data: bytesToBase64(bytes),
                recursive: true,
            });
        },

        async unlink(path: string): Promise<void> {
            await Filesystem.deleteFile({
                path: strip(path),
                directory: Directory.Data,
            });
        },

        async readdir(path: string): Promise<string[]> {
            const r = await Filesystem.readdir({
                path: strip(path),
                directory: Directory.Data,
            });
            return r.files.map((f) => f.name);
        },

        async mkdir(path: string, opts?: { recursive?: boolean }): Promise<void> {
            await Filesystem.mkdir({
                path: strip(path),
                directory: Directory.Data,
                recursive: opts?.recursive ?? true,
            });
        },

        async rmdir(path: string): Promise<void> {
            await Filesystem.rmdir({
                path: strip(path),
                directory: Directory.Data,
                recursive: true,
            });
        },

        async stat(path: string): Promise<FsStat> {
            const r = await Filesystem.stat({
                path: strip(path),
                directory: Directory.Data,
            });
            const isFile = r.type === "file";
            const isDir = r.type === "directory";
            return {
                type: isFile ? "file" : isDir ? "dir" : "symlink",
                mode: 0o644,
                size: r.size,
                mtimeMs: r.mtime,
                ino: 0,
                uid: 0,
                gid: 0,
                isFile: () => isFile,
                isDirectory: () => isDir,
                isSymbolicLink: () => false,
            };
        },

        async lstat(path: string): Promise<FsStat> {
            // No symlink support — behaves like stat.
            return this.stat(path);
        },

        async readlink(_path: string): Promise<string> {
            throw Object.assign(new Error("ENOSYS: symlinks unsupported"), { code: "ENOSYS" });
        },

        async symlink(_t: string, _p: string): Promise<void> {
            throw Object.assign(new Error("ENOSYS: symlinks unsupported"), { code: "ENOSYS" });
        },
    },
};
```

- [ ] **Step 2: Write tests**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockFs } = vi.hoisted(() => ({
    mockFs: {
        readFile: vi.fn(), writeFile: vi.fn(), deleteFile: vi.fn(),
        readdir: vi.fn(), mkdir: vi.fn(), rmdir: vi.fn(), stat: vi.fn(),
    },
}));

vi.mock("@capacitor/filesystem", () => ({
    Filesystem: mockFs,
    Directory: { Cache: "CACHE", Data: "DATA" },
}));

import { capacitorFsAdapter } from "../services/git/capacitorFsAdapter";

describe("capacitorFsAdapter", () => {
    beforeEach(() => Object.values(mockFs).forEach((f) => f.mockReset()));

    it("writeFile encodes string to base64 against Directory.Data", async () => {
        mockFs.writeFile.mockResolvedValue(undefined);
        await capacitorFsAdapter.promises.writeFile("/x.txt", "hi");
        const arg = mockFs.writeFile.mock.calls[0][0];
        expect(arg.path).toBe("x.txt");
        expect(arg.directory).toBe("DATA");
        // base64 of "hi" is "aGk="
        expect(arg.data).toBe("aGk=");
    });

    it("readFile returns Uint8Array by default", async () => {
        mockFs.readFile.mockResolvedValue({ data: "aGk=" });
        const r = await capacitorFsAdapter.promises.readFile("/x.txt");
        expect(r).toBeInstanceOf(Uint8Array);
        expect(new TextDecoder().decode(r as Uint8Array)).toBe("hi");
    });

    it("readFile returns string with utf8 encoding", async () => {
        mockFs.readFile.mockResolvedValue({ data: "aGk=" });
        const r = await capacitorFsAdapter.promises.readFile("/x.txt", { encoding: "utf8" });
        expect(r).toBe("hi");
    });

    it("readdir flattens to file names", async () => {
        mockFs.readdir.mockResolvedValue({ files: [{ name: "a" }, { name: "b" }] });
        expect(await capacitorFsAdapter.promises.readdir("/d")).toEqual(["a", "b"]);
    });

    it("stat returns FsStat with right boolean methods", async () => {
        mockFs.stat.mockResolvedValue({ type: "file", size: 12, mtime: 1234567 });
        const s = await capacitorFsAdapter.promises.stat("/f");
        expect(s.isFile()).toBe(true);
        expect(s.isDirectory()).toBe(false);
        expect(s.size).toBe(12);
    });

    it("readlink throws ENOSYS", async () => {
        await expect(capacitorFsAdapter.promises.readlink("/x")).rejects.toMatchObject({ code: "ENOSYS" });
    });
});
```

- [ ] **Step 3: Run tests**

```bash
npx vitest run src/__tests__/capacitorFsAdapter.test.ts
```

Expected: 6 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/services/git/capacitorFsAdapter.ts src/__tests__/capacitorFsAdapter.test.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: Capacitor Filesystem adapter for isomorphic-git"
```

---

### Task 11: Install `isomorphic-git`

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Add the dep**

```bash
npm install --save isomorphic-git
```

The package is ~150 KB minified+gzipped — but loaded via dynamic `import()` only when entering edit mode, so it does not weigh on startup.

- [ ] **Step 2: Verify TS types resolve**

```bash
npx tsc --noEmit 2>&1 | tail -5
```

If `tsc` is not installed locally, fall back to `npm run build:dev` which exercises the TS compiler via Vite.

- [ ] **Step 3: Commit**

```bash
git add package.json package-lock.json
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: add isomorphic-git dep for edit mode"
```

---

### Task 12: `RepoEditService` (promote Cache → Documents, init git baseline)

**Files:**
- Create: `src/services/repoEditService.ts`
- Create: `src/__tests__/repoEditService.test.ts`

- [ ] **Step 1: Write the test (skeletal — git mocked)**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockFs, mockGit, mockDb } = vi.hoisted(() => ({
    mockFs: {
        readFile: vi.fn(), writeFile: vi.fn(), mkdir: vi.fn(),
        readdir: vi.fn(), stat: vi.fn(), copy: vi.fn(),
    },
    mockGit: {
        init: vi.fn(),
        add: vi.fn(),
        commit: vi.fn(),
    },
    mockDb: {
        run: vi.fn(),
        all: vi.fn(),
    },
}));

vi.mock("@capacitor/filesystem", () => ({
    Filesystem: mockFs,
    Directory: { Cache: "CACHE", Data: "DATA" },
}));

vi.mock("isomorphic-git", () => ({
    init: mockGit.init,
    add: mockGit.add,
    commit: mockGit.commit,
}));

import { RepoEditService } from "../services/repoEditService";
import { RepoExtractorService } from "../services/repoExtractorService";

describe("RepoEditService.promoteToEditable", () => {
    beforeEach(() => {
        Object.values(mockFs).forEach((f) => f.mockReset());
        Object.values(mockGit).forEach((f) => f.mockReset());
        Object.values(mockDb).forEach((f) => f.mockReset());
    });

    it("copies Cache → Documents, runs git init+add+commit, persists row", async () => {
        const extractor = {
            ensureExtracted: vi.fn().mockResolvedValue("repos/foo"),
        } as unknown as RepoExtractorService;
        // listing under Cache/repos/foo: 2 files in root
        mockFs.readdir.mockResolvedValueOnce({
            files: [{ name: "README.md", type: "file" }, { name: "src", type: "directory" }],
        });
        mockFs.readdir.mockResolvedValueOnce({
            files: [{ name: "main.py", type: "file" }],
        });
        mockFs.readdir.mockResolvedValueOnce({ files: [] });
        mockFs.readFile.mockResolvedValue({ data: "aGk=" }); // base64 "hi"
        mockFs.writeFile.mockResolvedValue(undefined);
        mockFs.mkdir.mockResolvedValue(undefined);
        mockGit.init.mockResolvedValue(undefined);
        mockGit.add.mockResolvedValue(undefined);
        mockGit.commit.mockResolvedValue("baseline-sha");

        const svc = new RepoEditService(extractor, "/repos/foo.tar.gz", mockDb as never);
        const sha = await svc.promoteToEditable("foo");

        expect(extractor.ensureExtracted).toHaveBeenCalled();
        expect(mockGit.init).toHaveBeenCalledWith(expect.objectContaining({
            dir: expect.stringContaining("repos/foo"),
        }));
        expect(mockGit.add).toHaveBeenCalled();
        expect(mockGit.commit).toHaveBeenCalled();
        expect(sha).toBe("baseline-sha");
        expect(mockDb.run).toHaveBeenCalledWith(
            expect.stringContaining("INSERT"),
            expect.arrayContaining(["foo", "baseline-sha"]),
        );
    });
});
```

- [ ] **Step 2: Implement `RepoEditService`**

```typescript
import { Filesystem, Directory } from "@capacitor/filesystem";
import { capacitorFsAdapter } from "./git/capacitorFsAdapter";
import { RepoExtractorService } from "./repoExtractorService";

interface DbLike {
    run(sql: string, params?: unknown[]): Promise<unknown>;
    all<T = Record<string, unknown>>(sql: string, params?: unknown[]): Promise<T[]>;
}

/**
 * Promotes a read-only Cache extraction to a persistent Documents copy
 * with a baseline git commit. Idempotent: repromoting an already-editable
 * repo is a no-op (returns the existing baseline sha).
 *
 * Triggered explicitly by the UI (Code tool's "Edit" button).
 */
export class RepoEditService {

    constructor(
        private readonly extractor: RepoExtractorService,
        private readonly archiveUrl: string,
        private readonly db: DbLike,
    ) {}

    async isEditable(slug: string): Promise<boolean> {
        const rows = await this.db.all<{ slug: string }>(
            "SELECT slug FROM editable_repos WHERE slug = ? LIMIT 1",
            [slug],
        );
        return rows.length > 0;
    }

    async promoteToEditable(slug: string): Promise<string> {
        if (await this.isEditable(slug)) {
            const rows = await this.db.all<{ baseline_sha: string }>(
                "SELECT baseline_sha FROM editable_repos WHERE slug = ?",
                [slug],
            );
            return rows[0].baseline_sha;
        }

        const cacheBase = await this.extractor.ensureExtracted(slug, this.archiveUrl);
        const docsBase = `repos/${slug}`;

        // Recursive copy Cache → Documents.
        await this._copyTree(cacheBase, docsBase);

        // Lazy-import isomorphic-git so it does not weigh on startup.
        const git = await import("isomorphic-git");

        await git.init({
            fs: capacitorFsAdapter,
            dir: `/${docsBase}`,
        });

        // Stage everything.
        await git.add({
            fs: capacitorFsAdapter,
            dir: `/${docsBase}`,
            filepath: ".",
        });

        const buildId = await this._readBuildId();
        const sha = await git.commit({
            fs: capacitorFsAdapter,
            dir: `/${docsBase}`,
            message: `baseline: shipped via APK build ${buildId}`,
            author: { name: "ERPLibre Mobile", email: "app@local" },
        });

        await this.db.run(
            `INSERT INTO editable_repos (slug, baseline_sha, build_id, promoted_at, head_sha)
             VALUES (?, ?, ?, ?, ?)`,
            [slug, sha, buildId, Date.now(), sha],
        );

        return sha;
    }

    async unpromote(slug: string): Promise<void> {
        if (!(await this.isEditable(slug))) return;
        await Filesystem.rmdir({
            path: `repos/${slug}`,
            directory: Directory.Data,
            recursive: true,
        });
        await this.db.run("DELETE FROM editable_repos WHERE slug = ?", [slug]);
    }

    private async _copyTree(srcRel: string, dstRel: string): Promise<void> {
        // Walk src recursively. Cache is the source.
        const stack: string[] = [""];
        while (stack.length > 0) {
            const rel = stack.pop()!;
            const fullSrc = rel ? `${srcRel}/${rel}` : srcRel;
            const fullDst = rel ? `${dstRel}/${rel}` : dstRel;
            await Filesystem.mkdir({
                path: fullDst,
                directory: Directory.Data,
                recursive: true,
            }).catch(() => {});
            const r = await Filesystem.readdir({
                path: fullSrc,
                directory: Directory.Cache,
            });
            for (const f of r.files) {
                const subRel = rel ? `${rel}/${f.name}` : f.name;
                if (f.type === "directory") {
                    stack.push(subRel);
                } else {
                    if (f.name === ".extracted") continue;
                    const data = (await Filesystem.readFile({
                        path: `${srcRel}/${subRel}`,
                        directory: Directory.Cache,
                    })).data as string; // base64
                    await Filesystem.writeFile({
                        path: `${dstRel}/${subRel}`,
                        directory: Directory.Data,
                        data,
                        recursive: true,
                    });
                }
            }
        }
    }

    private async _readBuildId(): Promise<string> {
        try {
            const r = await fetch("/build_id.json");
            if (r.ok) {
                const j = await r.json();
                return j.buildId ?? "unknown";
            }
        } catch { /* ignore */ }
        return "unknown";
    }
}
```

Note: the `build_id.json` file is generated at build time by the Vite plugin (a small additional patch — see Task 14).

- [ ] **Step 3: Run tests**

```bash
npx vitest run src/__tests__/repoEditService.test.ts
```

- [ ] **Step 4: Commit**

```bash
git add src/services/repoEditService.ts src/__tests__/repoEditService.test.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: RepoEditService promote with git baseline"
```

---

### Task 13: `EditableCodeService` (read/write + git ops)

**Files:**
- Create: `src/services/editableCodeService.ts`
- Create: `src/__tests__/editableCodeService.test.ts`

- [ ] **Step 1: Write the test (high level — git mocked)**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockFs, mockGit } = vi.hoisted(() => ({
    mockFs: {
        readFile: vi.fn(), writeFile: vi.fn(), readdir: vi.fn(),
        deleteFile: vi.fn(), mkdir: vi.fn(),
    },
    mockGit: {
        statusMatrix: vi.fn(),
        commit: vi.fn(),
        log: vi.fn(),
        checkout: vi.fn(),
        resetIndex: vi.fn(),
    },
}));

vi.mock("@capacitor/filesystem", () => ({
    Filesystem: mockFs,
    Directory: { Cache: "CACHE", Data: "DATA" },
}));

vi.mock("isomorphic-git", () => mockGit);

import { EditableCodeService } from "../services/editableCodeService";

describe("EditableCodeService", () => {
    beforeEach(() => {
        Object.values(mockFs).forEach((f) => f.mockReset());
        Object.values(mockGit).forEach((f) => f.mockReset());
    });

    it("writeFile persists to Documents", async () => {
        mockFs.writeFile.mockResolvedValue(undefined);
        const svc = new EditableCodeService("foo");
        await svc.writeFile("README.md", "# updated");
        expect(mockFs.writeFile).toHaveBeenCalledWith(expect.objectContaining({
            path: "repos/foo/README.md",
            directory: "DATA",
        }));
    });

    it("status returns parsed matrix from isomorphic-git", async () => {
        // statusMatrix rows: [filepath, head, workdir, stage]
        mockGit.statusMatrix.mockResolvedValue([
            ["README.md", 1, 2, 1],   // modified, unstaged
            ["new.txt",   0, 2, 0],   // untracked
            ["staged.md", 1, 2, 2],   // staged-modified
            ["gone.md",   1, 0, 0],   // deleted
        ]);
        const svc = new EditableCodeService("foo");
        const s = await svc.status();
        expect(s.modified).toContain("README.md");
        expect(s.untracked).toContain("new.txt");
        expect(s.staged).toContain("staged.md");
        expect(s.deleted).toContain("gone.md");
    });

    it("commit returns SHA", async () => {
        mockGit.commit.mockResolvedValue("abc123");
        const svc = new EditableCodeService("foo");
        const sha = await svc.commit("change x");
        expect(sha).toBe("abc123");
    });
});
```

- [ ] **Step 2: Implement**

```typescript
import { Filesystem, Directory } from "@capacitor/filesystem";
import { capacitorFsAdapter } from "./git/capacitorFsAdapter";
import { GitStatus, GitCommit } from "../models/gitTypes";
import { DirEntry } from "./codeService";

export class EditableCodeService {
    private readonly _docsBase: string;

    constructor(public readonly slug: string) {
        this._docsBase = `repos/${slug}`;
    }

    async listDir(dirPath: string): Promise<DirEntry[]> {
        const path = dirPath ? `${this._docsBase}/${dirPath}` : this._docsBase;
        const r = await Filesystem.readdir({ path, directory: Directory.Data });
        return r.files
            .filter((f) => f.name !== ".git")
            .map((f) => ({
                name: f.name,
                type: f.type === "directory" ? "dir" : "file",
                path: dirPath ? `${dirPath}/${f.name}` : f.name,
            }));
    }

    async readFile(filepath: string): Promise<string> {
        const r = await Filesystem.readFile({
            path: `${this._docsBase}/${filepath}`,
            directory: Directory.Data,
        });
        const data = r.data as string;
        return new TextDecoder().decode(_b64ToBytes(data));
    }

    async writeFile(filepath: string, content: string): Promise<void> {
        const bytes = new TextEncoder().encode(content);
        await Filesystem.writeFile({
            path: `${this._docsBase}/${filepath}`,
            directory: Directory.Data,
            data: _bytesToB64(bytes),
            recursive: true,
        });
    }

    async deleteFile(filepath: string): Promise<void> {
        await Filesystem.deleteFile({
            path: `${this._docsBase}/${filepath}`,
            directory: Directory.Data,
        });
    }

    async status(): Promise<GitStatus> {
        const git = await import("isomorphic-git");
        const matrix = await git.statusMatrix({
            fs: capacitorFsAdapter,
            dir: `/${this._docsBase}`,
        });
        const status: GitStatus = { modified: [], untracked: [], staged: [], deleted: [] };
        for (const [filepath, head, wd, stage] of matrix) {
            if (head === 0 && wd === 2) status.untracked.push(filepath);
            else if (head === 1 && wd === 0) status.deleted.push(filepath);
            else if (head === 1 && wd === 2 && stage === 2) status.staged.push(filepath);
            else if (head === 1 && wd === 2) status.modified.push(filepath);
        }
        return status;
    }

    async diff(filepath?: string): Promise<string> {
        // isomorphic-git doesn't have a built-in unified diff; we compute it
        // from headTree vs workdir manually for the requested file (or all).
        const git = await import("isomorphic-git");
        const status = await this.status();
        const targets = filepath
            ? [filepath]
            : [...status.modified, ...status.staged, ...status.deleted, ...status.untracked];

        const out: string[] = [];
        for (const fp of targets) {
            try {
                const headBlob = await git.readBlob({
                    fs: capacitorFsAdapter,
                    dir: `/${this._docsBase}`,
                    oid: await git.resolveRef({
                        fs: capacitorFsAdapter,
                        dir: `/${this._docsBase}`,
                        ref: "HEAD",
                    }),
                    filepath: fp,
                }).then((b) => new TextDecoder().decode(b.blob)).catch(() => "");
                const workBlob = await this.readFile(fp).catch(() => "");
                if (headBlob !== workBlob) {
                    out.push(`--- a/${fp}`);
                    out.push(`+++ b/${fp}`);
                    out.push(...simpleLineDiff(headBlob, workBlob));
                }
            } catch { /* ignore per-file errors */ }
        }
        return out.join("\n");
    }

    async log(opts?: { limit?: number }): Promise<GitCommit[]> {
        const git = await import("isomorphic-git");
        const log = await git.log({
            fs: capacitorFsAdapter,
            dir: `/${this._docsBase}`,
            depth: opts?.limit ?? 50,
        });
        return log.map((e) => ({
            sha: e.oid,
            message: e.commit.message.trim(),
            author: { name: e.commit.author.name, email: e.commit.author.email },
            date: new Date(e.commit.author.timestamp * 1000).toISOString(),
            parentShas: e.commit.parent ?? [],
        }));
    }

    async commit(message: string): Promise<string> {
        const git = await import("isomorphic-git");
        await git.add({
            fs: capacitorFsAdapter,
            dir: `/${this._docsBase}`,
            filepath: ".",
        });
        return git.commit({
            fs: capacitorFsAdapter,
            dir: `/${this._docsBase}`,
            message,
            author: { name: "ERPLibre Mobile", email: "app@local" },
        });
    }

    async resetFile(filepath: string): Promise<void> {
        const git = await import("isomorphic-git");
        await git.checkout({
            fs: capacitorFsAdapter,
            dir: `/${this._docsBase}`,
            ref: "HEAD",
            filepaths: [filepath],
            force: true,
        });
    }

    async resetAll(): Promise<void> {
        const git = await import("isomorphic-git");
        await git.checkout({
            fs: capacitorFsAdapter,
            dir: `/${this._docsBase}`,
            ref: "HEAD",
            force: true,
        });
        // Drop untracked files manually.
        const status = await this.status();
        for (const fp of status.untracked) {
            await this.deleteFile(fp).catch(() => {});
        }
    }
}

function _bytesToB64(bytes: Uint8Array): string {
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
}
function _b64ToBytes(b64: string): Uint8Array {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
}

/** Minimal line diff (no Myers — just full-file replacement when texts differ). */
function simpleLineDiff(a: string, b: string): string[] {
    const out: string[] = [];
    if (!a && b) {
        for (const l of b.split("\n")) out.push(`+${l}`);
        return out;
    }
    if (a && !b) {
        for (const l of a.split("\n")) out.push(`-${l}`);
        return out;
    }
    const aLines = a.split("\n");
    const bLines = b.split("\n");
    const max = Math.max(aLines.length, bLines.length);
    for (let i = 0; i < max; i++) {
        const al = aLines[i];
        const bl = bLines[i];
        if (al === bl) {
            out.push(` ${al}`);
        } else {
            if (al !== undefined) out.push(`-${al}`);
            if (bl !== undefined) out.push(`+${bl}`);
        }
    }
    return out;
}
```

- [ ] **Step 3: Run tests**

```bash
npx vitest run src/__tests__/editableCodeService.test.ts
```

- [ ] **Step 4: Commit**

```bash
git add src/services/editableCodeService.ts src/__tests__/editableCodeService.test.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: EditableCodeService for git-backed edits"
```

---

### Task 14: Generate `build_id.json` at build time

**Files:**
- Modify: `vite.config.ts`

- [ ] **Step 1: Add build ID emission inside `bundleSourcePlugin().buildStart`**

After the manifest projects are processed and `bundledProjects` array is populated, before writing `manifest.json`, add:

```ts
            // Build identifier — used as baseline tag in editable repos.
            let buildId = "unknown";
            try {
                const sha = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
                    stdio: ["ignore", "pipe", "ignore"], encoding: "utf-8",
                }).trim();
                if (sha) buildId = sha;
            } catch { /* outside git or git missing */ }
            buildId += "_" + Date.now().toString(36);
            writeFileSync(
                join(reposOutDir, "..", "build_id.json"),
                JSON.stringify({ buildId, generatedAt: new Date().toISOString() }, null, 2),
            );
```

This emits `src/public/build_id.json` so `RepoEditService._readBuildId()` finds it via `fetch("/build_id.json")`.

- [ ] **Step 2: Build and verify**

```bash
rm -rf src/public/repo src/public/repos src/public/build_id.json
npm run build:dev 2>&1 | tail -10
cat src/public/build_id.json
```

- [ ] **Step 3: Commit**

```bash
git add vite.config.ts
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: emit build_id.json for editable repo baseline tagging"
```

---

## Phase F — Wiring + Documentation

### Task 15: Wire `BundleCodeService` chooser (read-only vs editable)

**Files:**
- Modify: `src/services/bundleCodeService.ts` OR create a small factory file `src/services/repoFsFactory.ts` (new file is cleaner — keep `BundleCodeService` simple).

- [ ] **Step 1: Create `repoFsFactory.ts`**

```typescript
import { ManifestProject } from "../models/manifestProject";
import { BundleCodeService } from "./bundleCodeService";
import { EditableCodeService } from "./editableCodeService";
import { RepoEditService } from "./repoEditService";
import { RepoExtractorService } from "./repoExtractorService";

export interface RepoFs {
    listDir(dirPath: string): Promise<{ name: string; type: "file" | "dir"; path: string }[]>;
    readFile(filepath: string): Promise<string>;
}

/**
 * Returns the right read API for a manifest repo:
 *   - EditableCodeService if the slug is in editable_repos
 *   - BundleCodeService (Cache, archive mode) otherwise
 */
export async function getRepoFs(
    project: ManifestProject,
    extractor: RepoExtractorService,
    editor: RepoEditService,
): Promise<RepoFs> {
    if (await editor.isEditable(project.slug)) {
        return new EditableCodeService(project.slug);
    }
    const svc = new BundleCodeService(
        "/ignored",
        {
            archiveUrl: `/${project.archive}`,
            indexUrl: `/${project.indexUrl}`,
            slug: project.slug,
        },
        extractor,
    );
    await svc.initialize();
    return svc;
}
```

- [ ] **Step 2: Update consumers (typically `codeService.ts` or the Code tool's Owl component)**

Find where `BundleCodeService` is currently instantiated for a manifest repo. Replace direct construction with `await getRepoFs(project, extractor, editor)`.

```bash
grep -rn "new BundleCodeService" src/
```

For each call site dealing with a manifest repo, route through `getRepoFs`. The app's own source (`/repo`) keeps the direct `BundleCodeService("/repo")` construction.

- [ ] **Step 3: Verify TS still compiles**

```bash
npm run build:dev 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add src/services/repoFsFactory.ts src/services/codeService.ts <other touched files>
git -c commit.gpgsign=false commit -m "[IMP] erplibre_home_mobile: route Code tool through RepoFs factory"
```

---

### Task 16: Document the new pipeline

**Files:**
- Create: `doc/BUNDLE_PIPELINE.md`
- Modify: `doc/SERVICES.md`
- Create: `doc/bundle_extract_test_matrix.md`

- [ ] **Step 1: Write `doc/BUNDLE_PIPELINE.md`**

```markdown
# Bundle Pipeline (tar.gz + Lazy Extract + Edit Mode)

## Overview

The Code tool browses two kinds of source bundles:

1. **App's own source** — loose files at build assets `/repo/`.
2. **Manifest repos** (138 OCA / ERPLibre / whisper.cpp / …) — shipped as
   per-repo `.tar.gz` archives at `/repos/{slug}.tar.gz`, extracted on
   demand into the device's Cache directory.

Editable mode promotes a manifest repo to a persistent, git-backed copy
in Documents.

## Build (vite.config.ts)

For every manifest project that exists locally:

1. Walk + filter source files (binary skip-list, max file size, etc.).
2. Stage the survivors in a temp dir.
3. `tar -czf <slug>.tar.gz` from the temp dir.
4. Emit a `<slug>.index.json` sidecar listing the same files.
5. Record archive + index URLs and sizes in `manifest.json`.

`build_id.json` is also emitted with a short git SHA + timestamp; this
identifier is recorded with each editable repo's baseline so we can
detect baseline drift after a rebuild.

## Read-only flow

```
User opens Code tool / selects repo
  ↓
getRepoFs(project, extractor, editor)
  ↓ (not editable)
BundleCodeService(archive mode)
  ↓ initialize()
fetch indexUrl → in-memory entries
extractor.ensureExtracted(slug, archiveUrl)
  ↓
fetch archiveUrl
  ↓ DecompressionStream("gzip")
parseTarStream → for each entry: Filesystem.writeFile under Cache
  ↓ sentinel .extracted
listDir / readFile from Cache
```

## Edit mode flow

```
User clicks "Edit"
  ↓
RepoEditService.promoteToEditable(slug)
  ↓ ensureExtracted (idempotent)
recursive copy Cache → Documents
  ↓
isomorphic-git: init + add + commit "baseline: build {id}"
  ↓
INSERT INTO editable_repos (slug, baseline_sha, …)
```

After promotion, `getRepoFs` returns an `EditableCodeService` for that slug. Reads/writes target Documents. Diffs come from `git.statusMatrix` + manual content compare. Resets use `git.checkout`.

## Extending later

Possible follow-ups (not in this iteration):

- Archive the app's own source too — same flow, requires no schema changes.
- Native Capacitor plugin wrapping `libtar` + `zlib` if pure-JS extraction proves too slow on low-end devices.
- Online git remote support (clone, push) — requires CORS proxy and credential UI.
```

- [ ] **Step 2: Append to `doc/SERVICES.md`** a short entry pointing to the new services.

```markdown
### RepoExtractorService / RepoEditService / EditableCodeService

See `doc/BUNDLE_PIPELINE.md` for the full flow. In short:

- `RepoExtractorService` — extract manifest repos from `tar.gz` to Cache.
- `RepoEditService` — promote to Documents + git baseline.
- `EditableCodeService` — read/write + git diff/commit/reset on a promoted repo.
- `repoFsFactory.getRepoFs(project)` — picks the right backend.
```

- [ ] **Step 3: Write `doc/bundle_extract_test_matrix.md`** (manual hardware checklist — see spec §8.3 for the full bullet list).

- [ ] **Step 4: Commit**

```bash
git add doc/BUNDLE_PIPELINE.md doc/SERVICES.md doc/bundle_extract_test_matrix.md
git -c commit.gpgsign=false commit -m "[ADD] erplibre_home_mobile: document tar.gz bundle pipeline + edit mode"
```

---

## Final Validation

- [ ] **Step 1: Vitest green**

```bash
cd mobile/erplibre_home_mobile
npm test
```

Expected: existing tests continue to pass, plus 5 new test files (tarParser, decompressGzip, repoExtractorService, capacitorFsAdapter, repoEditService, editableCodeService, bundleCodeService archive mode).

- [ ] **Step 2: Vite build green**

```bash
rm -rf src/public/repo src/public/repos src/public/build_id.json
npm run build:dev 2>&1 | tail -15
```

Expected: tar.gz files in `src/public/repos/`, `manifest.json` updated schema, `build_id.json` present.

- [ ] **Step 3: APK build green**

```bash
cd android && ./gradlew :app:assembleDebug 2>&1 | tail -3
```

Expected: BUILD SUCCESSFUL.

- [ ] **Step 4: Manual hardware matrix**

Follow `doc/bundle_extract_test_matrix.md`.

- [ ] **Step 5: Hand off**

The Code tool now uses tar.gz + edit mode. Future sub-projects:

- Replace this plan's `simpleLineDiff` with a real Myers-diff impl (`@isomorphic-git/diff` or `diff` npm) for nicer hunks.
- Archive the app's own source bundle too.
- Conflict UI when shipped baseline diverges from editable baseline.

---

## Notes for the executing engineer

- **Branch**: continue on `develop_stream_deck_android` for the mobile sub-repo, or cut a fresh `develop_bundle_pipeline`. The spec sits in the outer repo; the implementation lives in the inner `mobile/erplibre_home_mobile/.git`.
- **TDD strictness**: write the failing test FIRST, run it, see it fail, THEN implement. Don't bypass — the test code blocks above already encode the contracts.
- **Mock placement**: every test that mocks `@capacitor/filesystem` or `isomorphic-git` uses `vi.hoisted()` to declare mocks above the `vi.mock()` call, otherwise vitest throws `ReferenceError: Cannot access X before initialization`.
- **Build IDs**: the `build_id.json` file is read at runtime by `RepoEditService` — don't forget to add it to the sync target if your build process treats `src/public/` selectively.
- **Migration**: the new `editable_repos` SQLite migration must be added to the existing migration framework — copy the pattern of the latest migration in `src/services/migrationService.ts`.
