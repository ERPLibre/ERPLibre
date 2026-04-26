# Stream Deck Mobile Plugin (Android USB Host) — Design

- **Status**: Draft
- **Date**: 2026-04-25
- **Author**: Mathieu Benoit (brainstormed with Claude)
- **Target**: `mobile/erplibre_home_mobile/` (Android, Capacitor 8, Owl 2.8)
- **Scope**: New custom Capacitor plugin `StreamDeckPlugin` + companion TS service. First sub-project of a 4-spec effort to bring `script/stream_deck/game_tiler.py` functionality to the mobile app.

## 1. Goals

Expose Elgato Stream Deck devices connected to an Android phone via USB OTG to the Owl mobile app. The plugin must:

1. Detect any of the seven supported Elgato Stream Deck models when plugged into the device (single deck or multiple via a powered OTG hub).
2. Provide a TypeScript bridge that lets Owl components draw arbitrary images on deck buttons, read button presses, and (where the model supports it) drive dials, LCD strips, info bars and capacitive touch points.
3. Persist device identity by USB serial number across replug and app restart, so per-deck preferences/layouts/snapshots survive disconnections.
4. Stay model-agnostic at the Owl layer through a capability-based API. New models added later require only a new `DeckSpec` plus, rarely, a new `DeckTransport` or `ImageEncoder`.

## 2. Non-Goals

- Porting the games (`game_*.py`) or the rest of the `Tiler` controller modes — those are sub-project #4.
- Replacing Linux desktop features (window tiling D-Bus, `wpctl`, gnome-shell extension reload). Sub-project #4 will redesign each tiler mode for Android and drop the ones that are pure desktop concepts.
- Bluetooth control — sub-project #3 (separate Capacitor plugin).
- Animations as a first-class plugin feature. Animations are an Owl-side concern (loop calls to `setKeyImage`); the plugin's writer queue coalesces frames so animations don't flood USB.
- iOS support. Capacitor 8 nominally targets iOS too, but iOS USB host APIs are heavily restricted and out of scope.

## 3. Decisions Log

The seven brainstorming choices that shape the rest of the design:

| # | Decision | Choice |
|---|----------|--------|
| 1 | Mobile connectivity strategy | USB OTG (mobile speaks HID directly to deck) |
| 2 | Linux desktop functionality | Drop / redo for Android |
| 3 | Models supported | All seven (Original v1, Original v2, Mini, MK.2, XL, Plus, Neo) |
| 4 | Image encoding split | TS `<canvas>` → JPEG bytes, Java fallback for v1/Mini BMP rotated |
| 5 | Multi-deck | Yes — multiple decks via powered OTG hub |
| 6 | API shape | Unified, capability-based (`getDeckInfo()` exposes capabilities) |
| 7 | Deck identity | Persistent USB serial number |

## 4. Stream Deck USB Facts (reference)

Vendor ID `0x0fd9`. Product IDs and image format per model:

| Model | PID | Keys | Key image | Format | Special |
|-------|-----|------|-----------|--------|---------|
| Original v1 | `0x0060` | 15 (5×3) | 72×72 | BMP BGR rot 180° | — |
| Mini | `0x0063` | 6 (3×2) | 80×80 | BMP BGR rot 270° | — |
| Original v2 | `0x006d` | 15 (5×3) | 72×72 | JPEG | — |
| XL | `0x006c` | 32 (8×4) | 96×96 | JPEG | — |
| MK.2 | `0x0080` | 15 (5×3) | 72×72 | JPEG | — |
| Plus | `0x0084` | 8 (4×2) | 120×120 | JPEG | 4 dials, LCD 800×100 JPEG, capacitive touch on LCD |
| Neo | `0x009a` | 8 (4×2) | 96×96 | JPEG | 2 capacitive touch points, 2 LCD info bars |

Transports:

- **TransportV1** — Original v1, Mini. HID OUT pages of 8191 bytes, gen-1 page header.
- **TransportV2** — Original v2, MK.2, XL, Plus, Neo. HID OUT pages of 1024 bytes, gen-2 page header.

Feature reports (over `controlTransfer` request type `0x21`/`0xa1`):

- `0x03 0x08 <pct>` — set brightness (0..100).
- `0x03 0x02` — reset (clears all key images).
- `0x06` (v1) / `0x05` (v2+) — read serial number.
- `0x06` / `0x05` — read firmware version (different sub-id depending on gen).

## 5. Architecture (Strategy Pattern)

### 5.1 File layout

```
mobile/erplibre_home_mobile/android/app/src/main/java/ca/erplibre/home/streamdeck/
├── StreamDeckPlugin.java          # @CapacitorPlugin — entry, dispatches to sessions
├── DeckRegistry.java              # productId → DeckSpec
├── DeckSpec.java                  # immutable: model, rows, cols, dial_count,
│                                  #   key_image {w,h,format}, lcd, infobars, touchpoints,
│                                  #   transport class, encoder class, capabilities
├── DeckSession.java               # one connected deck: UsbDeviceConnection +
│                                  #   reader thread + writer thread + writer queue
├── transport/
│   ├── DeckTransport.java         # interface
│   ├── TransportV1.java           # gen-1 paginate (8191b) + headers
│   └── TransportV2.java           # gen-2 paginate (1024b) + headers
├── encoder/
│   ├── ImageEncoder.java          # interface: encodeForKey(rgba|jpeg|png) → byte[]
│   ├── JpegEncoder.java           # Bitmap.compress(JPEG, 90) for v2/MK.2/XL/Plus/Neo
│   └── BmpEncoder.java            # PNG → Bitmap → BGR raw → rotate(180° v1, 270° Mini)
├── lcd/
│   └── LcdEncoder.java            # JPEG full 800×100 (Plus) and Neo info bars 248×58
├── usb/
│   ├── UsbHotplugReceiver.java    # ATTACHED/DETACHED broadcast (registered in onResume)
│   └── UsbPermissionRequester.java # PendingIntent + permission broadcast
└── events/
    └── EventEmitter.java          # JSObject helpers for plugin notifyListeners
```

```
mobile/erplibre_home_mobile/src/plugins/
└── streamDeckPlugin.ts            # registerPlugin<StreamDeckPluginApi> wrapper
```

### 5.2 Threading model (per `DeckSession`)

- **Reader thread** — blocking `bulkTransfer(IN)` loop. Parses report bytes against the spec, emits `keyChanged` / `dialRotated` / `dialPressed` / `lcdTouched` / `neoTouched` via `EventEmitter`. Stops when the session closes.
- **Writer thread** — consumes a `WriterQueue` of `WriteJob`. One job at a time, in order, blocking on bulk OUT writes to keep page ordering deterministic.
- **WriterQueue coalescing** — each job has a slot key (`"key:N"`, `"lcd"`, `"infobar:0|1"`). When a new job arrives for a slot that already has a pending job, the pending one is removed from the queue and its TS Promise resolves with `{dropped: true}`. The new job is appended. Result: animations driven by Owl never flood USB; the most recent state per slot wins.
- **Permission `BroadcastReceiver`** — main thread, triggers `connectDevice()` once `EXTRA_PERMISSION_GRANTED == true`.
- **Discovery / hotplug `BroadcastReceiver`** — main thread, registered dynamically in the plugin's `load()`. Listens for `ACTION_USB_DEVICE_ATTACHED` / `ACTION_USB_DEVICE_DETACHED`. Filters by vendor `0x0fd9`.

### 5.3 Connection lifecycle

```
plugin.load()
  └─ register UsbHotplugReceiver (ATTACHED + DETACHED)
  └─ scan UsbManager.getDeviceList() for vendor 0x0fd9
        for each device → DeckSession.attach(spec)
              ├─ if !hasPermission → requestPermission(PendingIntent)
              ├─ on granted: openConnection, claim interface,
              │              read serial via feature report
              ├─ start reader thread
              ├─ start writer thread
              └─ emit "deckConnected" {deckId=serial, info}

USB DETACHED broadcast
  └─ session = sessions.lookup(usbDevicePath)
        ├─ session.close() → kill threads, drain writer queue with reject("disconnected"),
        │                    release interface, close UsbDeviceConnection
        └─ emit "deckDisconnected" {deckId, reason: "usb_lost"}

USB ATTACHED broadcast (app already running)
  └─ same flow as discovery, single device
```

The intent-filter on the launcher Activity (see §7) makes the OS open the app on plug-in if it's not running, and lets the user grant persistent permission via the system "Open with this app by default" checkbox.

## 6. TypeScript API (`src/plugins/streamDeckPlugin.ts`)

```typescript
import { registerPlugin, PluginListenerHandle } from "@capacitor/core";

export type DeckModel =
  | "original_v1" | "original_v2" | "mini"
  | "mk2" | "xl" | "plus" | "neo";

export type DeckImageFormat = "jpeg" | "bmp_bgr_rot180" | "bmp_bgr_rot270";

export interface DeckInfo {
  deckId: string;          // serial number, persistent
  model: DeckModel;
  productId: number;
  rows: number;
  cols: number;
  keyCount: number;
  keyImage: { w: number; h: number; format: DeckImageFormat };
  dialCount: number;       // 0 except Plus (4)
  lcd: { w: number; h: number } | null;            // Plus only
  infoBars: { w: number; h: number; count: number } | null;  // Neo only
  touchPoints: number;     // Neo (2); Plus uses lcd touch
  firmwareVersion: string;
  capabilities: string[];  // subset of ["keys", "dials", "lcd", "infobars", "touchpoints"]
}

export interface KeyEvent { deckId: string; key: number; pressed: boolean; }
export interface DialRotateEvent { deckId: string; dial: number; delta: number; }
export interface DialPressEvent { deckId: string; dial: number; pressed: boolean; }
export interface LcdTouchEvent {
  deckId: string;
  type: "short" | "long" | "drag";
  x: number; y: number;
  xEnd?: number; yEnd?: number;
}
export interface NeoTouchEvent { deckId: string; index: number; pressed: boolean; }
export interface DeckLifecycleEvent { deckId: string; info?: DeckInfo; reason?: string; }

export interface StreamDeckPluginApi {
  // Discovery + lifecycle
  listDecks(): Promise<{ decks: DeckInfo[] }>;
  getDeckInfo(opts: { deckId: string }): Promise<DeckInfo>;
  requestPermission(opts: { deckId: string }): Promise<{ granted: boolean }>;
  reset(opts: { deckId: string }): Promise<void>;
  setBrightness(opts: { deckId: string; percent: number }): Promise<void>;

  // Image (capability "keys")
  setKeyImage(opts: {
    deckId: string;
    key: number;
    bytes: string;       // base64
    format: "jpeg" | "png";
  }): Promise<{ dropped?: boolean }>;
  clearKey(opts: { deckId: string; key: number }): Promise<void>;
  clearAllKeys(opts: { deckId: string }): Promise<void>;

  // LCD (capability "lcd")
  setLcdImage(opts: { deckId: string; bytes: string }): Promise<{ dropped?: boolean }>;
  setLcdRegion(opts: {
    deckId: string;
    x: number; y: number; w: number; h: number;
    bytes: string;
  }): Promise<{ dropped?: boolean }>;

  // Info bars (capability "infobars")
  setInfoBar(opts: { deckId: string; index: 0 | 1; bytes: string }): Promise<{ dropped?: boolean }>;

  // Events (one signature per event name)
  addListener(eventName: "deckConnected", listener: (ev: DeckLifecycleEvent) => void): Promise<PluginListenerHandle>;
  addListener(eventName: "deckDisconnected", listener: (ev: DeckLifecycleEvent) => void): Promise<PluginListenerHandle>;
  addListener(eventName: "permissionDenied", listener: (ev: DeckLifecycleEvent) => void): Promise<PluginListenerHandle>;
  addListener(eventName: "keyChanged", listener: (ev: KeyEvent) => void): Promise<PluginListenerHandle>;
  addListener(eventName: "dialRotated", listener: (ev: DialRotateEvent) => void): Promise<PluginListenerHandle>;
  addListener(eventName: "dialPressed", listener: (ev: DialPressEvent) => void): Promise<PluginListenerHandle>;
  addListener(eventName: "lcdTouched", listener: (ev: LcdTouchEvent) => void): Promise<PluginListenerHandle>;
  addListener(eventName: "neoTouched", listener: (ev: NeoTouchEvent) => void): Promise<PluginListenerHandle>;
}

export const StreamDeckPlugin = registerPlugin<StreamDeckPluginApi>("StreamDeckPlugin");
```

Notes:

- `bytes` is base64. Capacitor's bridge serializes `Uint8Array` poorly; the rest of the project's custom plugins (Whisper, OCR, RawHttp) all pass binary as base64.
- `format: "png"` is required for v1/Mini key images and triggers BMP-rotate conversion in Java. `format: "jpeg"` is direct passthrough for v2+ models. Sending `"jpeg"` to a v1/Mini deck rejects with `"format_mismatch:bmp_model_requires_png"`.
- `setKeyImage` resolves with `{dropped: true}` when the writer queue coalesces the job (a newer image arrived for the same key first). This is success, not failure — Owl can ignore the field.

## 7. AndroidManifest.xml + USB device filter

Additions:

```xml
<uses-feature android:name="android.hardware.usb.host" android:required="false" />

<activity ...>
  <intent-filter>
    <action android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED" />
  </intent-filter>
  <meta-data
    android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED"
    android:resource="@xml/streamdeck_devices" />
</activity>
```

`res/xml/streamdeck_devices.xml`:

```xml
<resources>
  <usb-device vendor-id="4057" product-id="96"  /> <!-- 0x0060 Original v1 -->
  <usb-device vendor-id="4057" product-id="99"  /> <!-- 0x0063 Mini -->
  <usb-device vendor-id="4057" product-id="108" /> <!-- 0x006c XL -->
  <usb-device vendor-id="4057" product-id="109" /> <!-- 0x006d Original v2 -->
  <usb-device vendor-id="4057" product-id="128" /> <!-- 0x0080 MK.2 -->
  <usb-device vendor-id="4057" product-id="132" /> <!-- 0x0084 Plus -->
  <usb-device vendor-id="4057" product-id="154" /> <!-- 0x009a Neo -->
</resources>
```

Permission UX:

- **Plug-in when app is closed**: OS shows a chooser if multiple apps declare the filter; selecting ERPLibre Home (and optionally checking "Open by default") launches the app and grants persistent permission for that device.
- **Plug-in when app is open**: hotplug receiver detects ATTACHED, calls `UsbManager.requestPermission(device, pendingIntent)`. The system shows a dialog "Allow ERPLibre Home to access Stream Deck XL?" (with optional "always" checkbox).

## 8. Image Pipeline + Rate Limiting

End-to-end flow for one key update:

```
Owl component renders new state
  ↓
streamDeckService.renderKey(deckId, key, drawCallback)
  ├─ off-screen <canvas width=spec.keyImage.w height=spec.keyImage.h>
  ├─ drawCallback(ctx) draws shape/text/icon
  ├─ for v2+ models: canvas.toBlob('image/jpeg', 0.9)
  ├─ for v1/Mini:    canvas.toBlob('image/png')
  └─ blob → arrayBuffer → base64
  ↓
StreamDeckPlugin.setKeyImage({deckId, key, bytes, format})
  ↓ Capacitor bridge (JSON)
StreamDeckPlugin.java @PluginMethod setKeyImage()
  ├─ session = sessions.get(deckId); reject "no_such_deck" if null
  ├─ if session.spec.encoder is BmpEncoder and format == "jpeg" → reject "format_mismatch"
  └─ session.writerQueue.offerCoalesce(new ImageJob(key, decodedBytes, format))
  ↓ writer thread loop
DeckSession.writerLoop:
  ├─ if BmpEncoder: decode PNG → Bitmap → BGR raw → rotate
  ├─ else (JpegEncoder passthrough): bytes used as-is
  ├─ transport.writeKeyImage(key, encodedBytes)
  │     └─ paginate into HID OUT pages, bulkTransfer each (timeout 500 ms)
  └─ resolve job's TS Promise, or reject on transport failure
```

Coalescing implementation sketch:

```java
class WriterQueue {
  private final Deque<WriteJob> queue = new ArrayDeque<>();
  private final Map<String, WriteJob> latest = new HashMap<>();

  public synchronized void offerCoalesce(WriteJob job) {
    String slot = job.slotKey();      // "key:5", "lcd", "infobar:0"
    WriteJob prev = latest.get(slot);
    if (prev != null) {
      queue.remove(prev);
      prev.resolveDropped();          // TS Promise resolves with {dropped: true}
    }
    queue.addLast(job);
    latest.put(slot, job);
    notify();
  }

  public synchronized WriteJob take() throws InterruptedException {
    while (queue.isEmpty()) wait();
    WriteJob job = queue.removeFirst();
    if (latest.get(job.slotKey()) == job) latest.remove(job.slotKey());
    return job;
  }
}
```

Realistic budgets (informed by python-elgato-streamdeck benchmarks at similar HID rates):

| Model | Achievable rate |
|-------|-----------------|
| MK.2 / XL / Original v2 | ~30 fps full deck |
| Plus | ~20 fps with LCD updates, ~50 fps keys-only |
| Neo | ~30 fps keys, info bars sparse |
| v1 / Mini | ~10 fps (Java BMP rotate overhead) |

This is sufficient for the games in `script/stream_deck/game_*.py` (5–15 fps in the current Linux implementation).

## 9. Error Handling

| Condition | Detection | Reaction |
|-----------|-----------|----------|
| Permission denied | `EXTRA_PERMISSION_GRANTED == false` in broadcast | Emit `permissionDenied`, do not open session, expose deck via `listDecks()` with `permission: "denied"` |
| Unknown product ID | `DeckRegistry.lookup() == null` | Log warning, skip device |
| `claimInterface()` returns false | OS / other app holds the device | Emit `permissionDenied` with `reason="interface_busy"`, retry once after 500 ms |
| Disconnect mid-write | `bulkTransfer < 0` or exception | Writer thread fail-fast, drain queue rejecting `"disconnected"`, `session.close()`, emit `deckDisconnected` with `reason="usb_lost"` |
| Image too large for spec | Pre-encode TS check + Java job-receive guard | Reject Promise `"image_oversized"` |
| Wrong format for model | Magic-byte check Java side (BmpEncoder receives non-PNG) | Reject `"format_mismatch:bmp_model_requires_png"` |
| Reader thread bulk timeout | Normal idle, no key activity | Continue loop |
| Reader thread USB error | Non-timeout `bulkTransfer < 0` | Stop reader, trigger disconnect flow |
| PNG corrupted | `BitmapFactory.decodeByteArray() == null` | Reject `"image_decode_failed"` |
| Duplicate session for same serial | Defensive (USB enforces uniqueness) | Close old, open new, emit `deckReconnected` |
| App backgrounded | `onPause` | Sessions stay alive (Android keeps USB while process cached) |
| App destroyed | `onDestroy` | Close all sessions, unregister receivers |

## 10. Testing

### 10.1 JVM unit tests (Gradle `./gradlew testDebugUnitTest`)

- `BmpEncoderTest` — feed ARGB 80×80 fixture, assert binary equality with golden BMP for Mini and v1 (rotation correctness).
- `JpegEncoderTest` — feed ARGB inputs, assert output is valid JPEG (magic bytes, decodable round-trip via `BitmapFactory`).
- `TransportV1PaginationTest` / `TransportV2PaginationTest` — feed 5 KB synthetic image, assert page count, header bytes, padding behaviour, page order. `UsbDeviceConnection` mocked.
- `WriterQueueCoalescingTest` — three offers for the same slot resolve with two `dropped: true` and one real send.
- `DeckRegistryTest` — every supported productId maps to expected `DeckSpec`.

### 10.2 Vitest TS tests

- `streamDeckService.test.ts` — discovery flow, multi-deck mux, capability filtering, image render pipeline using a Canvas mock. Capacitor plugin bridge mocked.

### 10.3 Manual hardware matrix

`mobile/erplibre_home_mobile/doc/streamdeck_test_matrix.md` — checklist run against each physical device the developer owns:

- Connect / disconnect / replug → expected lifecycle events
- `setKeyImage` with a chequerboard test pattern bearing the key index → visual check
- `setBrightness` 0 / 50 / 100
- Key down / up reporting per key (full coverage)
- (Plus) dial rotate ±, dial press, LCD short / long / drag touch, LCD region update
- (Neo) info bar update, capacitive touch press / release
- `reset` clears all images
- Replug → reconnect with same `deckId` (serial)

Hardware tests are not in CI — no runner has a device.

## 11. Out of Scope / Follow-Up Sub-Projects

This spec only covers sub-project #1 (the plugin). The full mobile port still needs:

- **#2 — Stream Deck service (TS)**. `src/services/streamDeckService.ts`: deck registry observable, capability gating, model-aware image renderer, event multiplexer to Owl. Owns the off-screen canvases.
- **#3 — Bluetooth Capacitor plugin**. Custom `BluetoothPlugin.java` wrapping `BluetoothAdapter` / `BluetoothLeScanner` for the BLUETOOTH mode of the tiler controller.
- **#4 — Tiler controller port (Owl)**. Replicates `script/stream_deck/game_tiler.py` modes adapted for Android: `IDLE` menu, `TIMER` (SQLite-backed stopwatches replacing gnome-tracker), `SOUND` (`AudioManager` replacing `wpctl`), `A11Y` (intent to system accessibility settings replacing gnome font scale), `BLUETOOTH` (uses #3), `TRANSLATOR` (reuses existing `WhisperPlugin` + `transcriptionService.ts`). `TILE`, `LAYOUT` and `DEV RELOAD` are dropped — no Android equivalents.

Each follow-up sub-project gets its own brainstorming → spec → plan cycle.

## 12. Open Questions (deferred to implementation plan)

- Exact reader-thread report-parsing offsets per model (need to be cross-checked against `python-elgato-streamdeck` source during implementation; the spec assumes the parsing tables there are correct).
- Whether to call `forceClaim=true` on `claimInterface()`. Default `false` is safer; revisit if real-device testing shows the kernel HID driver grabs the interface first.
- LCD touch event coordinate origin on Plus (top-left vs LCD-relative). To verify on hardware.
