# Stream Deck Mobile Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `StreamDeckPlugin` Capacitor plugin (Android USB Host) that exposes Elgato Stream Deck devices to the Owl mobile app, supporting the seven models, multi-deck, capability-based API, and persistent serial-based device identity.

**Architecture:** Strategy pattern. `StreamDeckPlugin` (Capacitor entry) → `DeckSession` (per-device threads + queue) → pluggable `DeckTransport` + `ImageEncoder`, selected from a `DeckRegistry` keyed by USB product ID. Pure-Java logic (registry, pagination, queue coalescing, BGR rotation) is unit-testable; `Bitmap`/USB-dependent pieces are wired through real device matrix testing.

**Tech Stack:**
- Android Capacitor 8 plugin (Java 11, JUnit 4.13.2)
- Android USB Host API (`UsbManager`, `UsbDeviceConnection`, `bulkTransfer`, `controlTransfer`)
- TypeScript bridge (`registerPlugin`)
- Vitest for TS-side tests

**Spec:** `docs/superpowers/specs/2026-04-25-streamdeck-mobile-plugin-design.md`

**Working dir for all paths:** `mobile/erplibre_home_mobile/` unless prefixed with `docs/`.

**Reference for protocol bytes:** When writing transports/encoders, cross-check exact header bytes, command IDs, and report offsets against [`python-elgato-streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck) source under `src/StreamDeck/Devices/` (`StreamDeckMini.py`, `StreamDeckOriginal.py`, `StreamDeckOriginalV2.py`, `StreamDeckXL.py`, `StreamDeckMK2.py`, `StreamDeckPlus.py`, `StreamDeckNeo.py`). The `_KEY_IMAGE_FORMAT`, `_REPORT_LENGTH_PROTOCOL`, and `IMAGE_REPORT_HEADER` constants there are the source of truth.

---

## Task 1: USB device filter resource

**Files:**
- Create: `android/app/src/main/res/xml/streamdeck_devices.xml`

- [ ] **Step 1: Create the XML file with all seven product IDs**

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <!-- Elgato vendor-id 0x0fd9 = 4057 -->
    <usb-device vendor-id="4057" product-id="96"  /> <!-- 0x0060 Original v1 -->
    <usb-device vendor-id="4057" product-id="99"  /> <!-- 0x0063 Mini -->
    <usb-device vendor-id="4057" product-id="108" /> <!-- 0x006c XL -->
    <usb-device vendor-id="4057" product-id="109" /> <!-- 0x006d Original v2 -->
    <usb-device vendor-id="4057" product-id="128" /> <!-- 0x0080 MK.2 -->
    <usb-device vendor-id="4057" product-id="132" /> <!-- 0x0084 Plus -->
    <usb-device vendor-id="4057" product-id="154" /> <!-- 0x009a Neo -->
</resources>
```

- [ ] **Step 2: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/res/xml/streamdeck_devices.xml
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: USB device filter resource"
```

---

## Task 2: AndroidManifest USB intent-filter

**Files:**
- Modify: `android/app/src/main/AndroidManifest.xml`

- [ ] **Step 1: Add `<uses-feature>` near other `uses-feature` blocks (after line 80 `android.hardware.location.gps`)**

```xml
    <!-- Stream Deck USB Host -->
    <uses-feature android:name="android.hardware.usb.host" android:required="false" />
```

- [ ] **Step 2: Add the `USB_DEVICE_ATTACHED` intent-filter inside the existing `MainActivity` element**

Locate the `<activity android:name=".MainActivity" ...>` block (line 14-28). Inside it, after the existing `intent-filter` for `MAIN`/`LAUNCHER`, add:

```xml
            <intent-filter>
                <action android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED" />
            </intent-filter>
            <meta-data
                android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED"
                android:resource="@xml/streamdeck_devices" />
```

- [ ] **Step 3: Verify the manifest still parses**

Run: `cd android && ./gradlew assembleDebug --dry-run`
Expected: `BUILD SUCCESSFUL` (no manifest errors). If gradle is slow, alternatively run `./gradlew :app:processDebugManifest`.

- [ ] **Step 4: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/AndroidManifest.xml
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: USB intent-filter for hotplug"
```

---

## Task 3: `DeckSpec` immutable data class

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/DeckSpec.java`

- [ ] **Step 1: Create the data class**

```java
package ca.erplibre.home.streamdeck;

import java.util.Collections;
import java.util.List;

/**
 * Immutable description of a Stream Deck model. One instance per supported model,
 * built once and stored in DeckRegistry. Instances are safely shareable across threads.
 */
public final class DeckSpec {
    public enum ImageFormat { JPEG, BMP_BGR_ROT180, BMP_BGR_ROT270 }
    public enum TransportKind { V1, V2 }

    public final String model;            // "mk2", "xl", "plus", "neo", "original_v1", "original_v2", "mini"
    public final int productId;           // 0x0080 etc.
    public final int rows;
    public final int cols;
    public final int keyCount;
    public final int keyImageW;
    public final int keyImageH;
    public final ImageFormat keyImageFormat;
    public final int dialCount;           // 0 except Plus (4)
    public final int lcdW;                // 0 if no LCD
    public final int lcdH;
    public final int infoBarW;            // 0 if no info bars
    public final int infoBarH;
    public final int infoBarCount;        // 0 except Neo (2)
    public final int touchPoints;         // 0 except Neo (2); Plus uses lcd touch
    public final TransportKind transport;
    public final List<String> capabilities; // subset of: keys, dials, lcd, infobars, touchpoints

    private DeckSpec(Builder b) {
        this.model = b.model;
        this.productId = b.productId;
        this.rows = b.rows;
        this.cols = b.cols;
        this.keyCount = b.rows * b.cols;
        this.keyImageW = b.keyImageW;
        this.keyImageH = b.keyImageH;
        this.keyImageFormat = b.keyImageFormat;
        this.dialCount = b.dialCount;
        this.lcdW = b.lcdW;
        this.lcdH = b.lcdH;
        this.infoBarW = b.infoBarW;
        this.infoBarH = b.infoBarH;
        this.infoBarCount = b.infoBarCount;
        this.touchPoints = b.touchPoints;
        this.transport = b.transport;
        this.capabilities = Collections.unmodifiableList(b.capabilities);
    }

    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        String model; int productId; int rows; int cols;
        int keyImageW; int keyImageH; ImageFormat keyImageFormat;
        int dialCount; int lcdW; int lcdH; int infoBarW; int infoBarH;
        int infoBarCount; int touchPoints; TransportKind transport;
        java.util.ArrayList<String> capabilities = new java.util.ArrayList<>();

        public Builder model(String v) { this.model = v; return this; }
        public Builder productId(int v) { this.productId = v; return this; }
        public Builder grid(int rows, int cols) { this.rows = rows; this.cols = cols; return this; }
        public Builder keyImage(int w, int h, ImageFormat f) { this.keyImageW = w; this.keyImageH = h; this.keyImageFormat = f; return this; }
        public Builder dials(int n) { this.dialCount = n; return this; }
        public Builder lcd(int w, int h) { this.lcdW = w; this.lcdH = h; return this; }
        public Builder infoBars(int w, int h, int count) { this.infoBarW = w; this.infoBarH = h; this.infoBarCount = count; return this; }
        public Builder touch(int n) { this.touchPoints = n; return this; }
        public Builder transport(TransportKind v) { this.transport = v; return this; }
        public Builder capability(String c) { this.capabilities.add(c); return this; }
        public DeckSpec build() { return new DeckSpec(this); }
    }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd android && ./gradlew :app:compileDebugJavaWithJavac`
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 3: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/DeckSpec.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: DeckSpec immutable model description"
```

---

## Task 4: `DeckRegistry` table + JUnit test

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/DeckRegistry.java`
- Create: `android/app/src/test/java/ca/erplibre/home/streamdeck/DeckRegistryTest.java`

- [ ] **Step 1: Write the failing test**

```java
package ca.erplibre.home.streamdeck;

import static org.junit.Assert.*;
import org.junit.Test;

public class DeckRegistryTest {
    @Test
    public void mk2_lookup_returns_correct_spec() {
        DeckSpec s = DeckRegistry.lookup(0x0080);
        assertNotNull(s);
        assertEquals("mk2", s.model);
        assertEquals(15, s.keyCount);
        assertEquals(72, s.keyImageW);
        assertEquals(DeckSpec.ImageFormat.JPEG, s.keyImageFormat);
        assertEquals(DeckSpec.TransportKind.V2, s.transport);
        assertTrue(s.capabilities.contains("keys"));
        assertEquals(0, s.dialCount);
    }

    @Test
    public void plus_has_dials_and_lcd() {
        DeckSpec s = DeckRegistry.lookup(0x0084);
        assertNotNull(s);
        assertEquals(4, s.dialCount);
        assertEquals(800, s.lcdW);
        assertEquals(100, s.lcdH);
        assertTrue(s.capabilities.contains("dials"));
        assertTrue(s.capabilities.contains("lcd"));
    }

    @Test
    public void neo_has_infobars_and_touchpoints() {
        DeckSpec s = DeckRegistry.lookup(0x009a);
        assertNotNull(s);
        assertEquals(2, s.infoBarCount);
        assertEquals(2, s.touchPoints);
        assertTrue(s.capabilities.contains("infobars"));
        assertTrue(s.capabilities.contains("touchpoints"));
    }

    @Test
    public void mini_uses_bmp_rot270() {
        DeckSpec s = DeckRegistry.lookup(0x0063);
        assertNotNull(s);
        assertEquals(DeckSpec.ImageFormat.BMP_BGR_ROT270, s.keyImageFormat);
        assertEquals(DeckSpec.TransportKind.V1, s.transport);
    }

    @Test
    public void original_v1_uses_bmp_rot180() {
        DeckSpec s = DeckRegistry.lookup(0x0060);
        assertNotNull(s);
        assertEquals(DeckSpec.ImageFormat.BMP_BGR_ROT180, s.keyImageFormat);
        assertEquals(DeckSpec.TransportKind.V1, s.transport);
    }

    @Test
    public void unknown_pid_returns_null() {
        assertNull(DeckRegistry.lookup(0xDEAD));
    }

    @Test
    public void all_seven_models_present() {
        int[] pids = {0x0060, 0x0063, 0x006c, 0x006d, 0x0080, 0x0084, 0x009a};
        for (int pid : pids) {
            assertNotNull("missing pid 0x" + Integer.toHexString(pid), DeckRegistry.lookup(pid));
        }
    }
}
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.DeckRegistryTest`
Expected: FAIL — `DeckRegistry` does not exist.

- [ ] **Step 3: Implement `DeckRegistry`**

```java
package ca.erplibre.home.streamdeck;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/** Maps Elgato USB product IDs to immutable DeckSpec. Built once at class load. */
public final class DeckRegistry {
    public static final int ELGATO_VENDOR_ID = 0x0fd9;

    private static final Map<Integer, DeckSpec> SPECS;

    static {
        Map<Integer, DeckSpec> m = new HashMap<>();

        m.put(0x0060, DeckSpec.builder()
            .model("original_v1").productId(0x0060)
            .grid(3, 5)
            .keyImage(72, 72, DeckSpec.ImageFormat.BMP_BGR_ROT180)
            .transport(DeckSpec.TransportKind.V1)
            .capability("keys")
            .build());

        m.put(0x0063, DeckSpec.builder()
            .model("mini").productId(0x0063)
            .grid(2, 3)
            .keyImage(80, 80, DeckSpec.ImageFormat.BMP_BGR_ROT270)
            .transport(DeckSpec.TransportKind.V1)
            .capability("keys")
            .build());

        m.put(0x006c, DeckSpec.builder()
            .model("xl").productId(0x006c)
            .grid(4, 8)
            .keyImage(96, 96, DeckSpec.ImageFormat.JPEG)
            .transport(DeckSpec.TransportKind.V2)
            .capability("keys")
            .build());

        m.put(0x006d, DeckSpec.builder()
            .model("original_v2").productId(0x006d)
            .grid(3, 5)
            .keyImage(72, 72, DeckSpec.ImageFormat.JPEG)
            .transport(DeckSpec.TransportKind.V2)
            .capability("keys")
            .build());

        m.put(0x0080, DeckSpec.builder()
            .model("mk2").productId(0x0080)
            .grid(3, 5)
            .keyImage(72, 72, DeckSpec.ImageFormat.JPEG)
            .transport(DeckSpec.TransportKind.V2)
            .capability("keys")
            .build());

        m.put(0x0084, DeckSpec.builder()
            .model("plus").productId(0x0084)
            .grid(2, 4)
            .keyImage(120, 120, DeckSpec.ImageFormat.JPEG)
            .dials(4)
            .lcd(800, 100)
            .transport(DeckSpec.TransportKind.V2)
            .capability("keys").capability("dials").capability("lcd")
            .build());

        m.put(0x009a, DeckSpec.builder()
            .model("neo").productId(0x009a)
            .grid(2, 4)
            .keyImage(96, 96, DeckSpec.ImageFormat.JPEG)
            .infoBars(248, 58, 2)
            .touch(2)
            .transport(DeckSpec.TransportKind.V2)
            .capability("keys").capability("infobars").capability("touchpoints")
            .build());

        SPECS = Collections.unmodifiableMap(m);
    }

    private DeckRegistry() {}

    public static DeckSpec lookup(int productId) {
        return SPECS.get(productId);
    }

    public static boolean isElgato(int vendorId) {
        return vendorId == ELGATO_VENDOR_ID;
    }
}
```

- [ ] **Step 4: Run the test, confirm pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.DeckRegistryTest`
Expected: `BUILD SUCCESSFUL`, 7 tests passed.

- [ ] **Step 5: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/DeckRegistry.java \
        android/app/src/test/java/ca/erplibre/home/streamdeck/DeckRegistryTest.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: DeckRegistry table for 7 models + tests"
```

---

## Task 5: `RgbaRotator` pure-Java rotation + JUnit test

This is the pure-logic core of `BmpEncoder`. Splitting it out keeps Bitmap-dependent code out of unit tests.

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/encoder/RgbaRotator.java`
- Create: `android/app/src/test/java/ca/erplibre/home/streamdeck/encoder/RgbaRotatorTest.java`

- [ ] **Step 1: Write the failing test**

```java
package ca.erplibre.home.streamdeck.encoder;

import static org.junit.Assert.*;
import org.junit.Test;

public class RgbaRotatorTest {

    /** Single red pixel ARGB 0xFFFF0000 → BGR bytes {0x00, 0x00, 0xFF}. */
    @Test
    public void single_pixel_argb_to_bgr() {
        int[] argb = {0xFFFF0000}; // red
        byte[] bgr = RgbaRotator.toBgrRotated(argb, 1, 1, 0);
        assertArrayEquals(new byte[]{0x00, 0x00, (byte) 0xFF}, bgr);
    }

    /**
     * 2×2 ARGB, no rotation:
     *   R G        BGR rows (top→bottom, left→right):
     *   B W        00 00 FF | 00 FF 00 | FF 00 00 | FF FF FF
     */
    @Test
    public void two_by_two_no_rotation() {
        int[] argb = {
            0xFFFF0000, 0xFF00FF00,
            0xFF0000FF, 0xFFFFFFFF
        };
        byte[] expected = {
            0x00, 0x00, (byte) 0xFF,   // R
            0x00, (byte) 0xFF, 0x00,   // G
            (byte) 0xFF, 0x00, 0x00,   // B
            (byte) 0xFF, (byte) 0xFF, (byte) 0xFF // W
        };
        assertArrayEquals(expected, RgbaRotator.toBgrRotated(argb, 2, 2, 0));
    }

    /**
     * 2×2 ARGB rotated 180° = pixel order reversed.
     *   R G  →  W B
     *   B W      G R
     */
    @Test
    public void two_by_two_rotated_180() {
        int[] argb = {
            0xFFFF0000, 0xFF00FF00,
            0xFF0000FF, 0xFFFFFFFF
        };
        byte[] out = RgbaRotator.toBgrRotated(argb, 2, 2, 180);
        // First output pixel = last input pixel (white)
        assertEquals((byte) 0xFF, out[0]);
        assertEquals((byte) 0xFF, out[1]);
        assertEquals((byte) 0xFF, out[2]);
        // Last output pixel = first input pixel (red)
        assertEquals(0x00, out[9]);
        assertEquals(0x00, out[10]);
        assertEquals((byte) 0xFF, out[11]);
    }

    /**
     * 2×3 ARGB rotated 270° (counterclockwise once = 90° clockwise three times):
     * input  (W=2, H=3):
     *   1 2
     *   3 4
     *   5 6
     * output (W=3, H=2) — 270° CCW takes (x, y) → (y, W-1-x):
     *   2 4 6
     *   1 3 5
     */
    @Test
    public void two_by_three_rotated_270() {
        int[] argb = {
            0x01010101, 0x02020202,
            0x03030303, 0x04040404,
            0x05050505, 0x06060606
        };
        byte[] out = RgbaRotator.toBgrRotated(argb, 2, 3, 270);
        // Output dim = 3 wide × 2 tall. Pixel 0 = input pixel 1 (val 0x02).
        assertEquals(0x02, out[0]);
        // Pixel 1 = input pixel 3 (val 0x04).
        assertEquals(0x04, out[3]);
        // Pixel 5 (last) = input pixel 4 (val 0x05).
        assertEquals(0x05, out[15]);
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejects_unsupported_rotation() {
        RgbaRotator.toBgrRotated(new int[]{0}, 1, 1, 45);
    }
}
```

- [ ] **Step 2: Run, confirm failure**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.encoder.RgbaRotatorTest`
Expected: FAIL — `RgbaRotator` does not exist.

- [ ] **Step 3: Implement `RgbaRotator`**

```java
package ca.erplibre.home.streamdeck.encoder;

/**
 * Pure-Java helper that converts an ARGB int[] (Android Bitmap pixel layout)
 * to a BGR byte[] with optional rotation. Used by BmpEncoder for v1 / Mini.
 *
 * Supported rotations: 0, 180, 270 (counterclockwise).
 *
 * Output layout: row-major BGR triplets, scanned left-to-right top-to-bottom
 * in the destination orientation.
 */
public final class RgbaRotator {

    private RgbaRotator() {}

    public static byte[] toBgrRotated(int[] argb, int w, int h, int rotation) {
        if (rotation != 0 && rotation != 180 && rotation != 270) {
            throw new IllegalArgumentException("rotation must be 0, 180, or 270 (got " + rotation + ")");
        }
        if (argb.length != w * h) {
            throw new IllegalArgumentException("argb length " + argb.length + " != " + w + "*" + h);
        }

        int outW, outH;
        if (rotation == 270) { outW = h; outH = w; }
        else                 { outW = w; outH = h; }

        byte[] out = new byte[outW * outH * 3];

        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                int pixel = argb[y * w + x];
                int b = pixel & 0xFF;
                int g = (pixel >> 8) & 0xFF;
                int r = (pixel >> 16) & 0xFF;

                int dstX, dstY;
                switch (rotation) {
                    case 180: dstX = w - 1 - x; dstY = h - 1 - y; break;
                    case 270: dstX = y;         dstY = w - 1 - x; break;
                    default:  dstX = x;         dstY = y;         break;
                }
                int dstOff = (dstY * outW + dstX) * 3;
                out[dstOff]     = (byte) b;
                out[dstOff + 1] = (byte) g;
                out[dstOff + 2] = (byte) r;
            }
        }
        return out;
    }
}
```

- [ ] **Step 4: Run, confirm pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.encoder.RgbaRotatorTest`
Expected: 5 tests passed.

- [ ] **Step 5: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/encoder/RgbaRotator.java \
        android/app/src/test/java/ca/erplibre/home/streamdeck/encoder/RgbaRotatorTest.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: RgbaRotator pure-Java BGR rotation"
```

---

## Task 6: `TransportV2` pagination + JUnit test

V2 transport (gen-2: Original v2, MK.2, XL, Plus, Neo). Each HID page = 1024 bytes total, 8-byte header + payload.

**Reference:** `python-elgato-streamdeck/src/StreamDeck/Devices/StreamDeckMK2.py`, look for `_REPORT_LENGTH` and `IMAGE_REPORT_HEADER`. Header layout:

```
byte 0: 0x02                    (HID report ID)
byte 1: 0x07                    (set image command)
byte 2: key index               (0..keyCount-1)
byte 3: 0x01 if last page else 0x00
byte 4-5: payload length (LE u16)
byte 6-7: page number (LE u16, starts at 0)
```

This task implements only pagination logic, not USB I/O. The output is a `List<byte[]>`, each 1024 bytes.

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/transport/DeckTransport.java`
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/transport/TransportV2.java`
- Create: `android/app/src/test/java/ca/erplibre/home/streamdeck/transport/TransportV2Test.java`

- [ ] **Step 1: Write the failing test**

```java
package ca.erplibre.home.streamdeck.transport;

import static org.junit.Assert.*;
import org.junit.Test;
import java.util.List;

public class TransportV2Test {

    @Test
    public void single_page_image_when_smaller_than_payload() {
        // Image of 100 bytes — fits in one page (payload room = 1024 - 8 = 1016).
        byte[] img = new byte[100];
        for (int i = 0; i < img.length; i++) img[i] = (byte) (i & 0xFF);

        List<byte[]> pages = TransportV2.paginateKeyImage(/*key=*/3, img);
        assertEquals(1, pages.size());

        byte[] p0 = pages.get(0);
        assertEquals(1024, p0.length);
        assertEquals(0x02, p0[0] & 0xFF);
        assertEquals(0x07, p0[1] & 0xFF);
        assertEquals(3,    p0[2] & 0xFF);            // key index
        assertEquals(0x01, p0[3] & 0xFF);            // last page flag
        assertEquals(100,  (p0[4] & 0xFF) | ((p0[5] & 0xFF) << 8));   // payload length LE
        assertEquals(0,    (p0[6] & 0xFF) | ((p0[7] & 0xFF) << 8));   // page 0
        // Payload starts at byte 8.
        assertEquals(0, p0[8] & 0xFF);
        assertEquals(99, p0[8 + 99] & 0xFF);
    }

    @Test
    public void multi_page_image_splits_correctly() {
        // 3000 bytes → ceil(3000 / 1016) = 3 pages.
        byte[] img = new byte[3000];
        for (int i = 0; i < img.length; i++) img[i] = (byte) (i & 0xFF);

        List<byte[]> pages = TransportV2.paginateKeyImage(/*key=*/0, img);
        assertEquals(3, pages.size());

        // Page 0: payload 1016, page=0, last=0
        assertEquals(0x00, pages.get(0)[3] & 0xFF);
        assertEquals(1016, (pages.get(0)[4] & 0xFF) | ((pages.get(0)[5] & 0xFF) << 8));
        assertEquals(0,    (pages.get(0)[6] & 0xFF) | ((pages.get(0)[7] & 0xFF) << 8));

        // Page 1: payload 1016, page=1, last=0
        assertEquals(0x00, pages.get(1)[3] & 0xFF);
        assertEquals(1016, (pages.get(1)[4] & 0xFF) | ((pages.get(1)[5] & 0xFF) << 8));
        assertEquals(1,    (pages.get(1)[6] & 0xFF) | ((pages.get(1)[7] & 0xFF) << 8));

        // Page 2: payload 968, page=2, last=1
        assertEquals(0x01, pages.get(2)[3] & 0xFF);
        assertEquals(968,  (pages.get(2)[4] & 0xFF) | ((pages.get(2)[5] & 0xFF) << 8));
        assertEquals(2,    (pages.get(2)[6] & 0xFF) | ((pages.get(2)[7] & 0xFF) << 8));
    }

    @Test
    public void exact_multiple_payload_creates_full_pages_with_last_flag_on_final() {
        // 2032 bytes = 2 * 1016 — exactly two full pages.
        byte[] img = new byte[2032];
        List<byte[]> pages = TransportV2.paginateKeyImage(0, img);
        assertEquals(2, pages.size());
        assertEquals(0x00, pages.get(0)[3] & 0xFF);
        assertEquals(0x01, pages.get(1)[3] & 0xFF);
        assertEquals(1016, (pages.get(1)[4] & 0xFF) | ((pages.get(1)[5] & 0xFF) << 8));
    }

    @Test
    public void last_page_payload_zero_padded() {
        byte[] img = new byte[10];
        for (int i = 0; i < img.length; i++) img[i] = (byte) 0xAA;
        List<byte[]> pages = TransportV2.paginateKeyImage(0, img);
        // Last 1006 bytes of the 1024-byte page should be 0 (padding after 8+10).
        byte[] p = pages.get(0);
        for (int i = 18; i < 1024; i++) {
            assertEquals("padding at " + i, 0, p[i]);
        }
    }
}
```

- [ ] **Step 2: Run, confirm failure**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.transport.TransportV2Test`
Expected: FAIL — class missing.

- [ ] **Step 3: Implement `DeckTransport` interface and `TransportV2`**

`DeckTransport.java`:

```java
package ca.erplibre.home.streamdeck.transport;

import java.util.List;

/**
 * Pagination strategy per Stream Deck generation. Only pure logic lives here;
 * USB I/O is performed by DeckSession.
 */
public interface DeckTransport {

    /** Split an encoded key image into HID OUT pages (full page size, header + payload + zero-pad). */
    List<byte[]> paginateKeyImage(int keyIndex, byte[] imageBytes);

    /**
     * Total page size including header. Used by DeckSession to size the bulk transfer buffer
     * and validate writes.
     */
    int pageSize();
}
```

`TransportV2.java`:

```java
package ca.erplibre.home.streamdeck.transport;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Gen-2 pagination (Original v2, MK.2, XL, Plus, Neo).
 * Page = 1024 bytes total = 8-byte header + 1016-byte payload.
 *
 * Header:
 *   byte 0: 0x02 (HID report ID)
 *   byte 1: 0x07 (set image command)
 *   byte 2: key index
 *   byte 3: 0x01 if last page else 0x00
 *   byte 4-5: payload length (LE u16)
 *   byte 6-7: page number (LE u16, starts at 0)
 */
public final class TransportV2 implements DeckTransport {

    public  static final int PAGE_SIZE     = 1024;
    public  static final int HEADER_SIZE   = 8;
    public  static final int PAYLOAD_SIZE  = PAGE_SIZE - HEADER_SIZE; // 1016

    @Override public int pageSize() { return PAGE_SIZE; }

    @Override
    public List<byte[]> paginateKeyImage(int keyIndex, byte[] imageBytes) {
        return paginateKeyImageStatic(keyIndex, imageBytes);
    }

    public static List<byte[]> paginateKeyImageStatic(int keyIndex, byte[] imageBytes) {
        if (imageBytes.length == 0) return Collections.emptyList();

        int pageCount = (imageBytes.length + PAYLOAD_SIZE - 1) / PAYLOAD_SIZE;
        List<byte[]> pages = new ArrayList<>(pageCount);

        int offset = 0;
        for (int p = 0; p < pageCount; p++) {
            int remaining = imageBytes.length - offset;
            int payloadLen = Math.min(PAYLOAD_SIZE, remaining);
            boolean isLast = (p == pageCount - 1);

            byte[] page = new byte[PAGE_SIZE]; // zero-init, gives padding
            page[0] = 0x02;
            page[1] = 0x07;
            page[2] = (byte) keyIndex;
            page[3] = (byte) (isLast ? 0x01 : 0x00);
            page[4] = (byte) (payloadLen & 0xFF);
            page[5] = (byte) ((payloadLen >> 8) & 0xFF);
            page[6] = (byte) (p & 0xFF);
            page[7] = (byte) ((p >> 8) & 0xFF);

            System.arraycopy(imageBytes, offset, page, HEADER_SIZE, payloadLen);
            pages.add(page);
            offset += payloadLen;
        }
        return pages;
    }
}
```

- [ ] **Step 4: Run, confirm pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.transport.TransportV2Test`
Expected: 4 tests passed.

- [ ] **Step 5: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/transport/ \
        android/app/src/test/java/ca/erplibre/home/streamdeck/transport/TransportV2Test.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: TransportV2 pagination (gen-2 page format)"
```

---

## Task 7: `TransportV1` pagination + JUnit test

V1 transport (Original v1, Mini). Larger pages (8191 bytes), different header layout. **Cross-check with `python-elgato-streamdeck/src/StreamDeck/Devices/StreamDeckOriginal.py`** for the exact `IMAGE_REPORT_HEADER` constants and `IMAGE_REPORT_LENGTH`.

The header documented there is 16 bytes for v1 with command 0x02, sub-command varying per image part:

```
byte 0: 0x02
byte 1: 0x01            (set image)
byte 2-3: page number (LE)
byte 4: 0x00 if not last, 0x01 if last
byte 5: key index
byte 6-15: zero
```

Verify by reading the python source at the start of this task.

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/transport/TransportV1.java`
- Create: `android/app/src/test/java/ca/erplibre/home/streamdeck/transport/TransportV1Test.java`

- [ ] **Step 1: Verify protocol details against the python reference**

```bash
# In a scratch dir, fetch the upstream constants for cross-check.
mkdir -p /tmp/streamdeck-ref && cd /tmp/streamdeck-ref
curl -sSL https://raw.githubusercontent.com/abcminiuser/python-elgato-streamdeck/master/src/StreamDeck/Devices/StreamDeckOriginal.py -o StreamDeckOriginal.py
curl -sSL https://raw.githubusercontent.com/abcminiuser/python-elgato-streamdeck/master/src/StreamDeck/Devices/StreamDeckMini.py     -o StreamDeckMini.py
grep -E "IMAGE_REPORT_HEADER|IMAGE_REPORT_LENGTH|KEY_IMAGE_FORMAT|KEY_PIXEL_HEIGHT|KEY_PIXEL_WIDTH" StreamDeckOriginal.py StreamDeckMini.py
```

Use the constants returned to confirm `PAGE_SIZE`, `HEADER_SIZE`, and the exact header byte layout. If the upstream constants differ from the values below, update `TransportV1` and tests accordingly before committing.

- [ ] **Step 2: Write the failing test (using the layout above; adjust if upstream differs)**

```java
package ca.erplibre.home.streamdeck.transport;

import static org.junit.Assert.*;
import org.junit.Test;
import java.util.List;

public class TransportV1Test {

    @Test
    public void single_page_smaller_than_payload() {
        byte[] img = new byte[100];
        for (int i = 0; i < img.length; i++) img[i] = (byte) (i & 0xFF);

        List<byte[]> pages = TransportV1.paginateKeyImage(/*key=*/2, img);
        assertEquals(1, pages.size());

        byte[] p = pages.get(0);
        assertEquals(TransportV1.PAGE_SIZE, p.length);
        assertEquals(0x02, p[0] & 0xFF);
        assertEquals(0x01, p[1] & 0xFF);
        assertEquals(0,    (p[2] & 0xFF) | ((p[3] & 0xFF) << 8));    // page 0
        assertEquals(0x01, p[4] & 0xFF);                              // last
        assertEquals(2,    p[5] & 0xFF);                              // key index
        assertEquals(99, p[16 + 99] & 0xFF); // payload starts at byte 16
    }

    @Test
    public void multi_page_splits_correctly() {
        byte[] img = new byte[20000];
        List<byte[]> pages = TransportV1.paginateKeyImage(/*key=*/0, img);
        // 8191 - 16 = 8175 payload per page. 20000 / 8175 = 3 pages.
        assertEquals(3, pages.size());
        assertEquals(0,    (pages.get(0)[2] & 0xFF) | ((pages.get(0)[3] & 0xFF) << 8));
        assertEquals(1,    (pages.get(1)[2] & 0xFF) | ((pages.get(1)[3] & 0xFF) << 8));
        assertEquals(2,    (pages.get(2)[2] & 0xFF) | ((pages.get(2)[3] & 0xFF) << 8));
        // Only last page has last-flag set.
        assertEquals(0x00, pages.get(0)[4] & 0xFF);
        assertEquals(0x00, pages.get(1)[4] & 0xFF);
        assertEquals(0x01, pages.get(2)[4] & 0xFF);
    }

    @Test
    public void empty_image_yields_no_pages() {
        assertTrue(TransportV1.paginateKeyImage(0, new byte[0]).isEmpty());
    }
}
```

- [ ] **Step 3: Run, confirm fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.transport.TransportV1Test`

- [ ] **Step 4: Implement `TransportV1`**

```java
package ca.erplibre.home.streamdeck.transport;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Gen-1 pagination (Original v1, Mini).
 * Page = 8191 bytes total = 16-byte header + 8175-byte payload.
 *
 * Header (cross-checked against python-elgato-streamdeck StreamDeckOriginal.py):
 *   byte 0: 0x02
 *   byte 1: 0x01 (set image)
 *   byte 2-3: page number (LE u16)
 *   byte 4: 0x01 if last page else 0x00
 *   byte 5: key index
 *   byte 6-15: reserved (zero)
 */
public final class TransportV1 implements DeckTransport {

    public  static final int PAGE_SIZE    = 8191;
    public  static final int HEADER_SIZE  = 16;
    public  static final int PAYLOAD_SIZE = PAGE_SIZE - HEADER_SIZE; // 8175

    @Override public int pageSize() { return PAGE_SIZE; }

    @Override
    public List<byte[]> paginateKeyImage(int keyIndex, byte[] imageBytes) {
        return paginateKeyImageStatic(keyIndex, imageBytes);
    }

    public static List<byte[]> paginateKeyImageStatic(int keyIndex, byte[] imageBytes) {
        if (imageBytes.length == 0) return Collections.emptyList();

        int pageCount = (imageBytes.length + PAYLOAD_SIZE - 1) / PAYLOAD_SIZE;
        List<byte[]> pages = new ArrayList<>(pageCount);

        int offset = 0;
        for (int p = 0; p < pageCount; p++) {
            int remaining = imageBytes.length - offset;
            int payloadLen = Math.min(PAYLOAD_SIZE, remaining);
            boolean isLast = (p == pageCount - 1);

            byte[] page = new byte[PAGE_SIZE];
            page[0] = 0x02;
            page[1] = 0x01;
            page[2] = (byte) (p & 0xFF);
            page[3] = (byte) ((p >> 8) & 0xFF);
            page[4] = (byte) (isLast ? 0x01 : 0x00);
            page[5] = (byte) keyIndex;
            // bytes 6..15 left as 0

            System.arraycopy(imageBytes, offset, page, HEADER_SIZE, payloadLen);
            pages.add(page);
            offset += payloadLen;
        }
        return pages;
    }
}
```

- [ ] **Step 5: Run, confirm pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.transport.TransportV1Test`
Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/transport/TransportV1.java \
        android/app/src/test/java/ca/erplibre/home/streamdeck/transport/TransportV1Test.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: TransportV1 pagination (gen-1 page format)"
```

---

## Task 8: `WriterQueue` with coalescing + JUnit test

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/WriterQueue.java`
- Create: `android/app/src/test/java/ca/erplibre/home/streamdeck/WriterQueueTest.java`

- [ ] **Step 1: Write the failing test**

```java
package ca.erplibre.home.streamdeck;

import static org.junit.Assert.*;
import org.junit.Test;
import java.util.concurrent.atomic.AtomicInteger;

public class WriterQueueTest {

    /** Minimal WriteJob impl for tests — just records "dropped" / "executed". */
    static class FakeJob extends WriteJob {
        final String slot;
        boolean droppedFlag = false;
        FakeJob(String slot) { this.slot = slot; }
        @Override public String slotKey() { return slot; }
        @Override public void resolveDropped() { droppedFlag = true; }
        @Override public void runTransport() { /* no-op for these tests */ }
    }

    @Test
    public void single_offer_then_take_returns_same_job() throws InterruptedException {
        WriterQueue q = new WriterQueue();
        FakeJob j = new FakeJob("key:0");
        q.offerCoalesce(j);
        assertSame(j, q.take());
        assertFalse(j.droppedFlag);
    }

    @Test
    public void second_offer_same_slot_drops_first() throws InterruptedException {
        WriterQueue q = new WriterQueue();
        FakeJob j1 = new FakeJob("key:5");
        FakeJob j2 = new FakeJob("key:5");
        q.offerCoalesce(j1);
        q.offerCoalesce(j2);
        // Only j2 should remain queued; j1 should be marked dropped.
        assertTrue(j1.droppedFlag);
        assertFalse(j2.droppedFlag);
        assertSame(j2, q.take());
    }

    @Test
    public void different_slots_do_not_coalesce() throws InterruptedException {
        WriterQueue q = new WriterQueue();
        FakeJob a = new FakeJob("key:0");
        FakeJob b = new FakeJob("key:1");
        q.offerCoalesce(a);
        q.offerCoalesce(b);
        assertFalse(a.droppedFlag);
        assertFalse(b.droppedFlag);
        assertSame(a, q.take());
        assertSame(b, q.take());
    }

    @Test
    public void take_blocks_until_offer() throws Exception {
        WriterQueue q = new WriterQueue();
        AtomicInteger taken = new AtomicInteger(0);
        Thread t = new Thread(() -> {
            try { q.take(); taken.incrementAndGet(); } catch (InterruptedException ignored) {}
        });
        t.start();
        Thread.sleep(50);
        assertEquals(0, taken.get());
        q.offerCoalesce(new FakeJob("x"));
        t.join(500);
        assertEquals(1, taken.get());
    }

    @Test
    public void close_drains_remaining_with_dropped() {
        WriterQueue q = new WriterQueue();
        FakeJob a = new FakeJob("key:0");
        FakeJob b = new FakeJob("key:1");
        q.offerCoalesce(a);
        q.offerCoalesce(b);
        q.closeAndDrainAsDropped();
        assertTrue(a.droppedFlag);
        assertTrue(b.droppedFlag);
    }
}
```

- [ ] **Step 2: Run, confirm fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.WriterQueueTest`

- [ ] **Step 3: Implement `WriteJob` and `WriterQueue`**

`WriteJob.java`:

```java
package ca.erplibre.home.streamdeck;

/**
 * Abstract unit of work for the writer thread. Concrete subclasses know how to
 * resolve their TS Promise (success / dropped / failed) and how to perform the
 * actual USB transport write.
 */
public abstract class WriteJob {
    /** Coalescing key. Same slot → newer job replaces older one in the queue. */
    public abstract String slotKey();

    /** Called when the queue drops this job in favor of a newer one. */
    public abstract void resolveDropped();

    /** Called by the writer thread to execute the USB write and resolve the Promise. */
    public abstract void runTransport();
}
```

`WriterQueue.java`:

```java
package ca.erplibre.home.streamdeck;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.Map;

/**
 * Bounded-by-coalescing queue of WriteJob. Offering a job whose slotKey matches
 * an already-queued job replaces the older one (which is resolved as dropped).
 *
 * Thread-safe: any number of producers, exactly one consumer (the writer thread).
 */
public final class WriterQueue {

    private final Deque<WriteJob> queue = new ArrayDeque<>();
    private final Map<String, WriteJob> latest = new HashMap<>();
    private boolean closed = false;

    public synchronized void offerCoalesce(WriteJob job) {
        if (closed) {
            job.resolveDropped();
            return;
        }
        WriteJob prev = latest.get(job.slotKey());
        if (prev != null) {
            queue.remove(prev);
            prev.resolveDropped();
        }
        queue.addLast(job);
        latest.put(job.slotKey(), job);
        notifyAll();
    }

    public synchronized WriteJob take() throws InterruptedException {
        while (queue.isEmpty() && !closed) wait();
        if (closed) throw new InterruptedException("queue closed");
        WriteJob job = queue.removeFirst();
        if (latest.get(job.slotKey()) == job) latest.remove(job.slotKey());
        return job;
    }

    public synchronized void closeAndDrainAsDropped() {
        closed = true;
        for (WriteJob j : queue) j.resolveDropped();
        queue.clear();
        latest.clear();
        notifyAll();
    }
}
```

- [ ] **Step 4: Run, confirm pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.WriterQueueTest`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/WriteJob.java \
        android/app/src/main/java/ca/erplibre/home/streamdeck/WriterQueue.java \
        android/app/src/test/java/ca/erplibre/home/streamdeck/WriterQueueTest.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: WriterQueue with per-slot coalescing"
```

---

## Task 9: `EventEmitter` helper

Thin wrapper to emit Capacitor plugin events with the typed payload shape.

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/events/EventEmitter.java`

- [ ] **Step 1: Implement**

```java
package ca.erplibre.home.streamdeck.events;

import com.getcapacitor.JSObject;

/**
 * Functional interface implemented by StreamDeckPlugin to expose the protected
 * notifyListeners(String, JSObject) bridge to the streamdeck.* package.
 */
public interface EventEmitter {
    void emit(String eventName, JSObject data);
}
```

- [ ] **Step 2: Verify compile**

Run: `cd android && ./gradlew :app:compileDebugJavaWithJavac`

- [ ] **Step 3: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/events/EventEmitter.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: EventEmitter SAM bridge"
```

---

## Task 10: `ImageEncoder`, `JpegEncoder`, `BmpEncoder`

`JpegEncoder` is a passthrough — TS already produced JPEG bytes via Canvas. `BmpEncoder` decodes the input PNG to a `Bitmap`, extracts ARGB, and routes through `RgbaRotator`.

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/encoder/ImageEncoder.java`
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/encoder/JpegEncoder.java`
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/encoder/BmpEncoder.java`

- [ ] **Step 1: Implement `ImageEncoder` interface**

```java
package ca.erplibre.home.streamdeck.encoder;

/**
 * Converts a TS-supplied image (JPEG or PNG bytes) into the model's
 * on-the-wire format ready for transport pagination.
 *
 * Implementations are stateless and shareable across decks of the same model.
 */
public interface ImageEncoder {
    /** Indicates which input format this encoder accepts ("jpeg" or "png"). */
    String inputFormat();

    /** Produces the bytes the deck wants on the wire (pre-pagination). */
    byte[] encode(byte[] inputBytes, int targetW, int targetH) throws ImageEncodeException;

    final class ImageEncodeException extends Exception {
        public ImageEncodeException(String msg) { super(msg); }
        public ImageEncodeException(String msg, Throwable cause) { super(msg, cause); }
    }
}
```

- [ ] **Step 2: Implement `JpegEncoder` (passthrough)**

```java
package ca.erplibre.home.streamdeck.encoder;

/**
 * Identity encoder for v2+ Stream Decks: TypeScript renders to <canvas> and
 * exports JPEG via canvas.toBlob('image/jpeg'). Java only forwards the bytes
 * to the transport pagination stage.
 *
 * The encoder validates the JPEG magic bytes to fail fast on malformed input.
 */
public final class JpegEncoder implements ImageEncoder {

    @Override public String inputFormat() { return "jpeg"; }

    @Override
    public byte[] encode(byte[] inputBytes, int targetW, int targetH) throws ImageEncodeException {
        if (inputBytes == null || inputBytes.length < 3) {
            throw new ImageEncodeException("image_decode_failed:empty_or_truncated");
        }
        if ((inputBytes[0] & 0xFF) != 0xFF || (inputBytes[1] & 0xFF) != 0xD8 || (inputBytes[2] & 0xFF) != 0xFF) {
            throw new ImageEncodeException("format_mismatch:bmp_model_requires_png");
        }
        return inputBytes;
    }
}
```

- [ ] **Step 3: Implement `BmpEncoder`**

```java
package ca.erplibre.home.streamdeck.encoder;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;

/**
 * BMP encoder for v1 / Mini Stream Decks. Accepts PNG bytes from TS,
 * decodes to ARGB via Android's BitmapFactory, then delegates rotation
 * + BGR conversion to RgbaRotator (pure Java, unit-tested).
 *
 * The deck firmware actually expects a fully-formed BMP file, including
 * the 54-byte BITMAPV3 header. The output of this method is that file.
 */
public final class BmpEncoder implements ImageEncoder {

    private final int rotationDegrees; // 180 for v1, 270 for Mini

    public BmpEncoder(int rotationDegrees) {
        if (rotationDegrees != 180 && rotationDegrees != 270) {
            throw new IllegalArgumentException("BmpEncoder rotation must be 180 or 270");
        }
        this.rotationDegrees = rotationDegrees;
    }

    @Override public String inputFormat() { return "png"; }

    @Override
    public byte[] encode(byte[] inputBytes, int targetW, int targetH) throws ImageEncodeException {
        if (inputBytes == null || inputBytes.length < 8) {
            throw new ImageEncodeException("image_decode_failed:empty_or_truncated");
        }
        // PNG magic check
        if ((inputBytes[0] & 0xFF) != 0x89 || (inputBytes[1] & 0xFF) != 0x50
                || (inputBytes[2] & 0xFF) != 0x4E || (inputBytes[3] & 0xFF) != 0x47) {
            throw new ImageEncodeException("format_mismatch:bmp_model_requires_png");
        }

        Bitmap bmp = BitmapFactory.decodeByteArray(inputBytes, 0, inputBytes.length);
        if (bmp == null) throw new ImageEncodeException("image_decode_failed");

        if (bmp.getWidth() != targetW || bmp.getHeight() != targetH) {
            Bitmap scaled = Bitmap.createScaledBitmap(bmp, targetW, targetH, true);
            bmp.recycle();
            bmp = scaled;
        }

        int[] argb = new int[targetW * targetH];
        bmp.getPixels(argb, 0, targetW, 0, 0, targetW, targetH);
        bmp.recycle();

        byte[] bgr = RgbaRotator.toBgrRotated(argb, targetW, targetH, rotationDegrees);
        int outW = (rotationDegrees == 270) ? targetH : targetW;
        int outH = (rotationDegrees == 270) ? targetW : targetH;
        return wrapAsBmpFile(bgr, outW, outH);
    }

    /**
     * Wraps raw BGR pixels in a 54-byte BITMAPINFOHEADER BMP file. The deck
     * firmware reads this exact layout. Rows are NOT padded because BGR width
     * is always a multiple of 4 for the supported sizes (72, 80).
     */
    static byte[] wrapAsBmpFile(byte[] bgr, int w, int h) {
        final int header = 54;
        final int rowBytes = w * 3;
        if (rowBytes % 4 != 0) {
            throw new IllegalStateException("BMP row " + rowBytes + " not 4-aligned for w=" + w);
        }
        int fileSize = header + bgr.length;
        byte[] out = new byte[fileSize];

        // BITMAPFILEHEADER (14 bytes)
        out[0] = 'B'; out[1] = 'M';
        writeLE32(out, 2, fileSize);
        // 6-9 reserved = 0
        writeLE32(out, 10, header);              // pixel offset

        // BITMAPINFOHEADER (40 bytes)
        writeLE32(out, 14, 40);                  // header size
        writeLE32(out, 18, w);
        writeLE32(out, 22, -h);                  // negative h = top-down rows (no flip)
        writeLE16(out, 26, 1);                   // planes
        writeLE16(out, 28, 24);                  // bpp
        writeLE32(out, 30, 0);                   // compression = BI_RGB
        writeLE32(out, 34, bgr.length);          // image size
        writeLE32(out, 38, 2835);                // x ppm
        writeLE32(out, 42, 2835);                // y ppm
        // 46-49 colors used = 0; 50-53 important colors = 0

        System.arraycopy(bgr, 0, out, header, bgr.length);
        return out;
    }

    private static void writeLE32(byte[] buf, int off, int v) {
        buf[off]     = (byte) (v & 0xFF);
        buf[off + 1] = (byte) ((v >> 8) & 0xFF);
        buf[off + 2] = (byte) ((v >> 16) & 0xFF);
        buf[off + 3] = (byte) ((v >> 24) & 0xFF);
    }
    private static void writeLE16(byte[] buf, int off, int v) {
        buf[off]     = (byte) (v & 0xFF);
        buf[off + 1] = (byte) ((v >> 8) & 0xFF);
    }
}
```

- [ ] **Step 4: Verify compile**

Run: `cd android && ./gradlew :app:compileDebugJavaWithJavac`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 5: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/encoder/ImageEncoder.java \
        android/app/src/main/java/ca/erplibre/home/streamdeck/encoder/JpegEncoder.java \
        android/app/src/main/java/ca/erplibre/home/streamdeck/encoder/BmpEncoder.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: ImageEncoder + JPEG passthrough + BMP wrapper"
```

---

## Task 11: `LcdEncoder` for Plus + Neo

The Plus LCD touch strip and Neo info bars take JPEG too. Plus full LCD goes via a single `0x0C` set-image command with extra header fields (region x, y, w, h). For Neo info bars, each bar is a separate command (different command byte; cross-check `StreamDeckNeo.py`).

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/lcd/LcdEncoder.java`
- Create: `android/app/src/test/java/ca/erplibre/home/streamdeck/lcd/LcdEncoderTest.java`

- [ ] **Step 1: Verify Plus + Neo LCD/info-bar protocol**

```bash
cd /tmp/streamdeck-ref
curl -sSL https://raw.githubusercontent.com/abcminiuser/python-elgato-streamdeck/master/src/StreamDeck/Devices/StreamDeckPlus.py -o StreamDeckPlus.py
curl -sSL https://raw.githubusercontent.com/abcminiuser/python-elgato-streamdeck/master/src/StreamDeck/Devices/StreamDeckNeo.py  -o StreamDeckNeo.py
grep -n -E "set_screen_image|TOUCHSCREEN|INFOBAR|IMAGE_REPORT|0x0[bcd]" StreamDeckPlus.py StreamDeckNeo.py | head -50
```

Use the constants there for header layout below. The LCD command on Plus is `0x0C` with a 16-byte header carrying x/y/w/h.

- [ ] **Step 2: Write the failing test (structure-level only — assert page header bytes and sizes)**

```java
package ca.erplibre.home.streamdeck.lcd;

import static org.junit.Assert.*;
import org.junit.Test;
import java.util.List;

public class LcdEncoderTest {

    @Test
    public void plus_full_lcd_paginates_with_correct_command_byte() {
        byte[] jpeg = new byte[5000];
        // Synthetic payload — bytes 0/1/2 are JPEG magic so JpegEncoder pre-validation
        // doesn't reject it if reused.
        jpeg[0] = (byte) 0xFF; jpeg[1] = (byte) 0xD8; jpeg[2] = (byte) 0xFF;
        List<byte[]> pages = LcdEncoder.paginatePlusLcd(0, 0, 800, 100, jpeg);
        assertFalse(pages.isEmpty());
        for (byte[] p : pages) {
            assertEquals(1024, p.length);
            assertEquals(0x02, p[0] & 0xFF);          // report id
            assertEquals(0x0C, p[1] & 0xFF);          // LCD command
        }
        // First page should encode region 0,0 800x100.
        byte[] p0 = pages.get(0);
        assertEquals(0,   (p0[2] & 0xFF) | ((p0[3] & 0xFF) << 8));
        assertEquals(0,   (p0[4] & 0xFF) | ((p0[5] & 0xFF) << 8));
        assertEquals(800, (p0[6] & 0xFF) | ((p0[7] & 0xFF) << 8));
        assertEquals(100, (p0[8] & 0xFF) | ((p0[9] & 0xFF) << 8));
        // Last page must have last-flag set.
        byte[] last = pages.get(pages.size() - 1);
        assertEquals(0x01, last[10] & 0xFF);
    }

    @Test(expected = IllegalArgumentException.class)
    public void plus_lcd_rejects_oversized_region() {
        LcdEncoder.paginatePlusLcd(0, 0, 801, 100, new byte[1]);
    }
}
```

- [ ] **Step 3: Run, confirm fail**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.lcd.LcdEncoderTest`

- [ ] **Step 4: Implement `LcdEncoder`**

```java
package ca.erplibre.home.streamdeck.lcd;

import java.util.ArrayList;
import java.util.List;

/**
 * Pagination for the Plus touchscreen LCD (800×100 JPEG) and the Neo info bars.
 *
 * Plus LCD wire format (cross-checked against python-elgato-streamdeck StreamDeckPlus.py):
 *   page = 1024 bytes total = 16-byte header + 1008-byte payload
 *   byte 0: 0x02
 *   byte 1: 0x0C   (touchscreen image set)
 *   byte 2-3:  x       (LE u16)
 *   byte 4-5:  y       (LE u16)
 *   byte 6-7:  w       (LE u16)
 *   byte 8-9:  h       (LE u16)
 *   byte 10:   isLast  (0x01 final, 0x00 otherwise)
 *   byte 11:   reserved (0)
 *   byte 12-13: page number (LE u16)
 *   byte 14-15: payload length (LE u16)
 *
 * The (x,y,w,h) fields are duplicated on every page (TS impl observed in
 * upstream library; matches what the firmware accepts).
 */
public final class LcdEncoder {

    public  static final int PAGE_SIZE     = 1024;
    public  static final int HEADER_SIZE   = 16;
    public  static final int PAYLOAD_SIZE  = PAGE_SIZE - HEADER_SIZE; // 1008

    public  static final int PLUS_LCD_W    = 800;
    public  static final int PLUS_LCD_H    = 100;

    private LcdEncoder() {}

    public static List<byte[]> paginatePlusLcd(int x, int y, int w, int h, byte[] jpegBytes) {
        if (x < 0 || y < 0 || w <= 0 || h <= 0
                || x + w > PLUS_LCD_W || y + h > PLUS_LCD_H) {
            throw new IllegalArgumentException(
                "lcd region (" + x + "," + y + "," + w + "," + h + ") out of bounds");
        }
        if (jpegBytes == null || jpegBytes.length == 0) {
            throw new IllegalArgumentException("empty jpeg bytes");
        }

        int pageCount = (jpegBytes.length + PAYLOAD_SIZE - 1) / PAYLOAD_SIZE;
        List<byte[]> pages = new ArrayList<>(pageCount);

        int offset = 0;
        for (int p = 0; p < pageCount; p++) {
            int remaining = jpegBytes.length - offset;
            int payloadLen = Math.min(PAYLOAD_SIZE, remaining);
            boolean isLast = (p == pageCount - 1);

            byte[] page = new byte[PAGE_SIZE];
            page[0] = 0x02;
            page[1] = 0x0C;
            writeLE16(page, 2, x);
            writeLE16(page, 4, y);
            writeLE16(page, 6, w);
            writeLE16(page, 8, h);
            page[10] = (byte) (isLast ? 0x01 : 0x00);
            page[11] = 0;
            writeLE16(page, 12, p);
            writeLE16(page, 14, payloadLen);

            System.arraycopy(jpegBytes, offset, page, HEADER_SIZE, payloadLen);
            pages.add(page);
            offset += payloadLen;
        }
        return pages;
    }

    private static void writeLE16(byte[] buf, int off, int v) {
        buf[off]     = (byte) (v & 0xFF);
        buf[off + 1] = (byte) ((v >> 8) & 0xFF);
    }
}
```

- [ ] **Step 5: Run, confirm pass**

Run: `cd android && ./gradlew :app:testDebugUnitTest --tests ca.erplibre.home.streamdeck.lcd.LcdEncoderTest`

- [ ] **Step 6: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/lcd/LcdEncoder.java \
        android/app/src/test/java/ca/erplibre/home/streamdeck/lcd/LcdEncoderTest.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: LcdEncoder for Plus touchscreen pagination"
```

---

## Task 12: `UsbPermissionRequester`

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/usb/UsbPermissionRequester.java`

- [ ] **Step 1: Implement**

```java
package ca.erplibre.home.streamdeck.usb;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;
import android.os.Build;
import android.util.Log;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Requests USB permission for one device at a time and resolves a future when
 * the system broadcast comes back. Pending requests are de-duplicated by
 * (vendorId, productId, deviceName) so concurrent attach events don't pile up.
 */
public final class UsbPermissionRequester {

    private static final String TAG = "StreamDeckPerm";
    private static final String ACTION = "ca.erplibre.home.streamdeck.USB_PERMISSION";

    private final Context context;
    private final UsbManager usb;
    private final Map<String, CompletableFuture<Boolean>> pending = new HashMap<>();
    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context ctx, Intent intent) {
            if (!ACTION.equals(intent.getAction())) return;
            UsbDevice dev = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
            boolean granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false);
            if (dev == null) return;
            String key = keyOf(dev);
            CompletableFuture<Boolean> fut;
            synchronized (pending) { fut = pending.remove(key); }
            if (fut != null) fut.complete(granted);
            else Log.w(TAG, "permission broadcast for unknown key " + key + " granted=" + granted);
        }
    };

    public UsbPermissionRequester(Context context, UsbManager usb) {
        this.context = context;
        this.usb = usb;
        IntentFilter filter = new IntentFilter(ACTION);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            context.registerReceiver(receiver, filter);
        }
    }

    public void close() {
        try { context.unregisterReceiver(receiver); } catch (IllegalArgumentException ignored) {}
        synchronized (pending) {
            for (CompletableFuture<Boolean> f : pending.values()) f.complete(false);
            pending.clear();
        }
    }

    public CompletableFuture<Boolean> request(UsbDevice device) {
        if (usb.hasPermission(device)) {
            return CompletableFuture.completedFuture(true);
        }
        String key = keyOf(device);
        CompletableFuture<Boolean> fut;
        synchronized (pending) {
            CompletableFuture<Boolean> existing = pending.get(key);
            if (existing != null) return existing;
            fut = new CompletableFuture<>();
            pending.put(key, fut);
        }
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) flags |= PendingIntent.FLAG_MUTABLE;
        PendingIntent pi = PendingIntent.getBroadcast(context, 0, new Intent(ACTION).setPackage(context.getPackageName()), flags);
        usb.requestPermission(device, pi);
        return fut;
    }

    private static String keyOf(UsbDevice d) {
        return d.getVendorId() + ":" + d.getProductId() + ":" + d.getDeviceName();
    }
}
```

- [ ] **Step 2: Verify compile**

Run: `cd android && ./gradlew :app:compileDebugJavaWithJavac`

- [ ] **Step 3: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/usb/UsbPermissionRequester.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: USB permission requester"
```

---

## Task 13: `UsbHotplugReceiver`

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/usb/UsbHotplugReceiver.java`

- [ ] **Step 1: Implement**

```java
package ca.erplibre.home.streamdeck.usb;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;
import android.os.Build;

import ca.erplibre.home.streamdeck.DeckRegistry;

/**
 * Receives USB attach / detach broadcasts for Elgato Stream Deck devices.
 * Filters by vendor 0x0fd9 before dispatching so unrelated devices don't trigger anything.
 *
 * Owner is responsible for register/unregister via attach()/detach().
 */
public final class UsbHotplugReceiver extends BroadcastReceiver {

    public interface Listener {
        void onDeckAttached(UsbDevice device);
        void onDeckDetached(UsbDevice device);
    }

    private final Listener listener;

    public UsbHotplugReceiver(Listener listener) { this.listener = listener; }

    public void attach(Context context) {
        IntentFilter f = new IntentFilter();
        f.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);
        f.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(this, f, Context.RECEIVER_NOT_EXPORTED);
        } else {
            context.registerReceiver(this, f);
        }
    }

    public void detach(Context context) {
        try { context.unregisterReceiver(this); } catch (IllegalArgumentException ignored) {}
    }

    @Override
    public void onReceive(Context ctx, Intent intent) {
        UsbDevice dev = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
        if (dev == null || !DeckRegistry.isElgato(dev.getVendorId())) return;
        if (UsbManager.ACTION_USB_DEVICE_ATTACHED.equals(intent.getAction())) {
            listener.onDeckAttached(dev);
        } else if (UsbManager.ACTION_USB_DEVICE_DETACHED.equals(intent.getAction())) {
            listener.onDeckDetached(dev);
        }
    }
}
```

- [ ] **Step 2: Verify compile**

Run: `cd android && ./gradlew :app:compileDebugJavaWithJavac`

- [ ] **Step 3: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/usb/UsbHotplugReceiver.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: USB hotplug receiver (Elgato-only filter)"
```

---

## Task 14: `DeckSession` (per-device threads + lifecycle)

This is the largest single file. It owns one `UsbDeviceConnection`, one reader thread, one writer thread, one `WriterQueue`, the encoders/transport instances, and the lifecycle hooks.

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/DeckSession.java`

- [ ] **Step 1: Implement**

```java
package ca.erplibre.home.streamdeck;

import android.hardware.usb.UsbConstants;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbInterface;
import android.hardware.usb.UsbManager;
import android.util.Log;

import com.getcapacitor.JSObject;

import java.util.List;

import ca.erplibre.home.streamdeck.encoder.BmpEncoder;
import ca.erplibre.home.streamdeck.encoder.ImageEncoder;
import ca.erplibre.home.streamdeck.encoder.JpegEncoder;
import ca.erplibre.home.streamdeck.events.EventEmitter;
import ca.erplibre.home.streamdeck.transport.DeckTransport;
import ca.erplibre.home.streamdeck.transport.TransportV1;
import ca.erplibre.home.streamdeck.transport.TransportV2;

/**
 * One open Stream Deck. Owns all per-device threads and resources.
 *
 * Lifecycle:
 *   constructor (no I/O)
 *   open(usbConnection, iface) — claim, read serial, start threads
 *   close() — kill threads, drain queue with rejected promises, release iface
 */
public final class DeckSession {

    private static final String TAG = "StreamDeckSession";
    private static final int    BULK_WRITE_TIMEOUT_MS = 500;
    private static final int    BULK_READ_TIMEOUT_MS  = 1000;

    private final DeckSpec spec;
    private final UsbDevice device;
    private final EventEmitter emitter;
    private final WriterQueue queue = new WriterQueue();
    private final DeckTransport transport;
    private final ImageEncoder encoder;

    private UsbDeviceConnection connection;
    private UsbInterface iface;
    private UsbEndpoint epIn;
    private UsbEndpoint epOut;
    private String serial = "";
    private String firmware = "";

    private Thread readerThread;
    private Thread writerThread;
    private volatile boolean running = false;

    public DeckSession(DeckSpec spec, UsbDevice device, EventEmitter emitter) {
        this.spec = spec;
        this.device = device;
        this.emitter = emitter;
        this.transport = (spec.transport == DeckSpec.TransportKind.V1) ? new TransportV1() : new TransportV2();
        this.encoder = chooseEncoder(spec);
    }

    private static ImageEncoder chooseEncoder(DeckSpec spec) {
        switch (spec.keyImageFormat) {
            case JPEG:            return new JpegEncoder();
            case BMP_BGR_ROT180:  return new BmpEncoder(180);
            case BMP_BGR_ROT270:  return new BmpEncoder(270);
            default: throw new IllegalStateException("unknown format " + spec.keyImageFormat);
        }
    }

    public DeckSpec spec()   { return spec; }
    public UsbDevice device(){ return device; }
    public String serial()   { return serial; }
    public String firmware() { return firmware; }

    public synchronized void open(UsbManager usb) throws DeckOpenException {
        if (running) return;

        // Find the HID interface.
        UsbInterface chosenIface = null;
        UsbEndpoint chosenIn = null, chosenOut = null;
        for (int i = 0; i < device.getInterfaceCount(); i++) {
            UsbInterface itf = device.getInterface(i);
            if (itf.getInterfaceClass() != UsbConstants.USB_CLASS_HID) continue;
            UsbEndpoint epi = null, epo = null;
            for (int e = 0; e < itf.getEndpointCount(); e++) {
                UsbEndpoint ep = itf.getEndpoint(e);
                if (ep.getDirection() == UsbConstants.USB_DIR_IN)  epi = ep;
                if (ep.getDirection() == UsbConstants.USB_DIR_OUT) epo = ep;
            }
            if (epi != null && epo != null) {
                chosenIface = itf; chosenIn = epi; chosenOut = epo; break;
            }
        }
        if (chosenIface == null) throw new DeckOpenException("no_hid_interface");

        connection = usb.openDevice(device);
        if (connection == null) throw new DeckOpenException("open_failed");
        if (!connection.claimInterface(chosenIface, /*forceClaim=*/true)) {
            connection.close();
            throw new DeckOpenException("interface_busy");
        }
        this.iface = chosenIface;
        this.epIn  = chosenIn;
        this.epOut = chosenOut;

        try {
            this.serial   = readSerial();
            this.firmware = readFirmware();
        } catch (Exception e) {
            Log.w(TAG, "feature read failed for " + device.getDeviceName(), e);
            this.serial = device.getSerialNumber() != null ? device.getSerialNumber() : "unknown";
            this.firmware = "unknown";
        }

        running = true;
        readerThread = new Thread(this::readerLoop, "deck-reader-" + serial);
        writerThread = new Thread(this::writerLoop, "deck-writer-" + serial);
        readerThread.setDaemon(true);
        writerThread.setDaemon(true);
        readerThread.start();
        writerThread.start();

        emitLifecycle("deckConnected", null);
    }

    public synchronized void close(String reason) {
        if (!running) return;
        running = false;
        queue.closeAndDrainAsDropped();
        if (readerThread != null) readerThread.interrupt();
        if (writerThread != null) writerThread.interrupt();
        if (connection != null) {
            try { connection.releaseInterface(iface); } catch (Exception ignored) {}
            try { connection.close(); } catch (Exception ignored) {}
        }
        emitLifecycle("deckDisconnected", reason);
    }

    public ImageEncoder encoder()   { return encoder; }
    public DeckTransport transport(){ return transport; }
    public WriterQueue queue()      { return queue; }

    /** Synchronously write all pages of a pre-paginated payload to the OUT endpoint. */
    public void writePages(List<byte[]> pages) throws DeckIoException {
        for (byte[] page : pages) {
            int sent = connection.bulkTransfer(epOut, page, page.length, BULK_WRITE_TIMEOUT_MS);
            if (sent != page.length) {
                throw new DeckIoException("bulk_write_short:" + sent + "/" + page.length);
            }
        }
    }

    /** Set brightness 0..100 via feature report. */
    public void setBrightness(int percent) throws DeckIoException {
        int p = Math.max(0, Math.min(100, percent));
        // Feature report: 0x03 0x08 <pct>. SET_REPORT request type 0x21,
        // request 0x09 (SET_REPORT), value (Feature << 8) | reportId.
        byte[] payload;
        if (spec.transport == DeckSpec.TransportKind.V2) {
            payload = new byte[32];
            payload[0] = 0x03; payload[1] = 0x08; payload[2] = (byte) p;
        } else {
            payload = new byte[17];
            payload[0] = 0x05; payload[1] = 0x55; payload[2] = (byte) 0xAA;
            payload[3] = (byte) 0xD1; payload[4] = 0x01; payload[5] = (byte) p;
        }
        int wValue = (0x03 << 8) | (payload[0] & 0xFF);
        int sent = connection.controlTransfer(0x21, 0x09, wValue, 0, payload, payload.length, 1000);
        if (sent < 0) throw new DeckIoException("set_brightness_failed:" + sent);
    }

    /** Reset (clear all key images) via feature report. */
    public void reset() throws DeckIoException {
        byte[] payload;
        if (spec.transport == DeckSpec.TransportKind.V2) {
            payload = new byte[32];
            payload[0] = 0x03; payload[1] = 0x02;
        } else {
            payload = new byte[17];
            payload[0] = 0x0B; payload[1] = 0x63;
        }
        int wValue = (0x03 << 8) | (payload[0] & 0xFF);
        int sent = connection.controlTransfer(0x21, 0x09, wValue, 0, payload, payload.length, 1000);
        if (sent < 0) throw new DeckIoException("reset_failed:" + sent);
    }

    private String readSerial() throws DeckIoException {
        // GET_REPORT (request type 0xa1, request 0x01), feature report ID per generation.
        byte[] buf = new byte[32];
        int reportId = (spec.transport == DeckSpec.TransportKind.V2) ? 0x06 : 0x03;
        int got = connection.controlTransfer(0xa1, 0x01, (0x03 << 8) | reportId, 0, buf, buf.length, 1000);
        if (got < 0) throw new DeckIoException("read_serial_failed:" + got);
        return parseAsciiAfterHeader(buf, /*headerLen=*/ (spec.transport == DeckSpec.TransportKind.V2) ? 2 : 5, got);
    }

    private String readFirmware() throws DeckIoException {
        byte[] buf = new byte[32];
        int reportId = (spec.transport == DeckSpec.TransportKind.V2) ? 0x05 : 0x04;
        int got = connection.controlTransfer(0xa1, 0x01, (0x03 << 8) | reportId, 0, buf, buf.length, 1000);
        if (got < 0) throw new DeckIoException("read_firmware_failed:" + got);
        return parseAsciiAfterHeader(buf, /*headerLen=*/ (spec.transport == DeckSpec.TransportKind.V2) ? 6 : 5, got);
    }

    private static String parseAsciiAfterHeader(byte[] buf, int headerLen, int totalLen) {
        StringBuilder sb = new StringBuilder();
        for (int i = headerLen; i < totalLen; i++) {
            byte b = buf[i];
            if (b == 0) break;
            if (b >= 0x20 && b < 0x7f) sb.append((char) b);
        }
        return sb.toString();
    }

    private void readerLoop() {
        // Buffer sized to spec's HID input report length (inferred from python lib;
        // safe upper bound covers all models).
        byte[] buf = new byte[64];
        while (running) {
            int got = connection.bulkTransfer(epIn, buf, buf.length, BULK_READ_TIMEOUT_MS);
            if (!running) break;
            if (got < 0) {
                // timeout (continue) or error (disconnect).
                if (got == -1) continue; // common timeout return on Android USB stack
                Log.w(TAG, "reader bulkTransfer error " + got + " — closing session");
                close("usb_lost");
                return;
            }
            parseInputReport(buf, got);
        }
    }

    /**
     * Parse one HID IN report. Layout differs per model — this dispatch handles
     * the common cases. Detailed offsets must be cross-checked against
     * python-elgato-streamdeck during integration testing.
     *
     * v1: report id 0x01 followed by 1 byte per key (1=pressed, 0=not).
     * v2+ keys: 0x01 0x00 <pad> followed by 1 byte per key.
     * Plus dial: 0x01 0x03 ...
     * Plus lcd touch: 0x01 0x02 ...
     * Neo touch: 0x01 0x04 ...
     */
    private void parseInputReport(byte[] buf, int len) {
        if (len < 2) return;
        int reportId = buf[0] & 0xFF;
        int subType = buf[1] & 0xFF;

        if (reportId == 0x01 && subType == 0x00) {
            // Key report. Keys start at offset 4 for V2, 1 for V1.
            int offset = (spec.transport == DeckSpec.TransportKind.V2) ? 4 : 1;
            for (int k = 0; k < spec.keyCount; k++) {
                if (offset + k >= len) break;
                boolean pressed = buf[offset + k] != 0;
                JSObject ev = new JSObject();
                ev.put("deckId", serial);
                ev.put("key", k);
                ev.put("pressed", pressed);
                emitter.emit("keyChanged", ev);
            }
        } else if (reportId == 0x01 && subType == 0x03 && spec.dialCount > 0) {
            // Plus dial. byte 4 = type (0=press, 1=rotate); subsequent bytes per dial.
            int kind = buf[4] & 0xFF;
            for (int d = 0; d < spec.dialCount; d++) {
                int v = buf[5 + d] & 0xFF;
                if (kind == 0x00) {
                    JSObject ev = new JSObject();
                    ev.put("deckId", serial);
                    ev.put("dial", d);
                    ev.put("pressed", v != 0);
                    emitter.emit("dialPressed", ev);
                } else if (kind == 0x01) {
                    int delta = (v >= 0x80) ? v - 0x100 : v;
                    if (delta == 0) continue;
                    JSObject ev = new JSObject();
                    ev.put("deckId", serial);
                    ev.put("dial", d);
                    ev.put("delta", delta);
                    emitter.emit("dialRotated", ev);
                }
            }
        } else if (reportId == 0x01 && subType == 0x02 && spec.lcdW > 0) {
            // Plus LCD touch. byte 4 = kind (1=short, 2=long, 3=drag).
            int kind = buf[4] & 0xFF;
            int x = (buf[6] & 0xFF) | ((buf[7] & 0xFF) << 8);
            int y = (buf[8] & 0xFF) | ((buf[9] & 0xFF) << 8);
            JSObject ev = new JSObject();
            ev.put("deckId", serial);
            ev.put("type", kind == 1 ? "short" : kind == 2 ? "long" : "drag");
            ev.put("x", x);
            ev.put("y", y);
            if (kind == 3) {
                int xe = (buf[10] & 0xFF) | ((buf[11] & 0xFF) << 8);
                int ye = (buf[12] & 0xFF) | ((buf[13] & 0xFF) << 8);
                ev.put("xEnd", xe); ev.put("yEnd", ye);
            }
            emitter.emit("lcdTouched", ev);
        } else if (reportId == 0x01 && subType == 0x04 && spec.touchPoints > 0) {
            // Neo touch points. Byte 5 = bitmask.
            int mask = buf[5] & 0xFF;
            for (int t = 0; t < spec.touchPoints; t++) {
                JSObject ev = new JSObject();
                ev.put("deckId", serial);
                ev.put("index", t);
                ev.put("pressed", (mask & (1 << t)) != 0);
                emitter.emit("neoTouched", ev);
            }
        }
    }

    private void writerLoop() {
        while (running) {
            try {
                WriteJob job = queue.take();
                if (!running) return;
                job.runTransport();
            } catch (InterruptedException e) {
                return; // closed
            } catch (Throwable t) {
                Log.w(TAG, "writer job error", t);
            }
        }
    }

    private void emitLifecycle(String name, String reason) {
        JSObject ev = new JSObject();
        ev.put("deckId", serial);
        if (reason != null) ev.put("reason", reason);
        emitter.emit(name, ev);
    }

    public static final class DeckOpenException extends Exception {
        public DeckOpenException(String msg) { super(msg); }
    }

    public static final class DeckIoException extends Exception {
        public DeckIoException(String msg) { super(msg); }
    }
}
```

- [ ] **Step 2: Verify compile**

Run: `cd android && ./gradlew :app:compileDebugJavaWithJavac`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 3: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/DeckSession.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: DeckSession (per-device threads + lifecycle)"
```

---

## Task 15: `StreamDeckPlugin` (Capacitor entry)

Wires the receivers, manages sessions keyed by USB device path AND serial, dispatches plugin methods.

**Files:**
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/StreamDeckPlugin.java`
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/ImageWriteJob.java`
- Create: `android/app/src/main/java/ca/erplibre/home/streamdeck/LcdWriteJob.java`

- [ ] **Step 1: Implement `ImageWriteJob`**

```java
package ca.erplibre.home.streamdeck;

import android.util.Base64;

import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;

import java.util.List;

import ca.erplibre.home.streamdeck.encoder.ImageEncoder;
import ca.erplibre.home.streamdeck.transport.DeckTransport;

/** Writes one key image: encode → paginate → write pages. Resolves the PluginCall. */
final class ImageWriteJob extends WriteJob {

    private final DeckSession session;
    private final int keyIndex;
    private final byte[] inputBytes;
    private final PluginCall call;

    ImageWriteJob(DeckSession session, int keyIndex, byte[] inputBytes, PluginCall call) {
        this.session = session;
        this.keyIndex = keyIndex;
        this.inputBytes = inputBytes;
        this.call = call;
    }

    @Override public String slotKey() { return "key:" + keyIndex; }

    @Override public void resolveDropped() {
        JSObject r = new JSObject();
        r.put("dropped", true);
        call.resolve(r);
    }

    @Override
    public void runTransport() {
        try {
            ImageEncoder enc = session.encoder();
            byte[] encoded = enc.encode(inputBytes, session.spec().keyImageW, session.spec().keyImageH);
            DeckTransport tx = session.transport();
            List<byte[]> pages = tx.paginateKeyImage(keyIndex, encoded);
            session.writePages(pages);
            JSObject r = new JSObject();
            r.put("dropped", false);
            call.resolve(r);
        } catch (ImageEncoder.ImageEncodeException e) {
            call.reject(e.getMessage());
        } catch (DeckSession.DeckIoException e) {
            call.reject(e.getMessage());
        } catch (Throwable t) {
            call.reject("image_write_failed:" + t.getMessage());
        }
    }
}
```

- [ ] **Step 1b: Implement `LcdWriteJob`**

```java
package ca.erplibre.home.streamdeck;

import android.util.Base64;

import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;

import java.util.List;

import ca.erplibre.home.streamdeck.lcd.LcdEncoder;

/**
 * Writes one Plus LCD region (full or partial). LCD bytes are JPEG already
 * (TS rendered them via Canvas), so there is no encode step — straight to
 * pagination + bulk OUT writes.
 */
final class LcdWriteJob extends WriteJob {

    private final DeckSession session;
    private final int x, y, w, h;
    private final byte[] jpegBytes;
    private final PluginCall call;
    private final String slotKey;

    LcdWriteJob(DeckSession session, int x, int y, int w, int h, byte[] jpegBytes,
                PluginCall call, String slotKey) {
        this.session = session;
        this.x = x; this.y = y; this.w = w; this.h = h;
        this.jpegBytes = jpegBytes;
        this.call = call;
        this.slotKey = slotKey;
    }

    @Override public String slotKey() { return slotKey; }

    @Override public void resolveDropped() {
        JSObject r = new JSObject();
        r.put("dropped", true);
        call.resolve(r);
    }

    @Override
    public void runTransport() {
        try {
            if (jpegBytes.length < 3
                    || (jpegBytes[0] & 0xFF) != 0xFF
                    || (jpegBytes[1] & 0xFF) != 0xD8
                    || (jpegBytes[2] & 0xFF) != 0xFF) {
                call.reject("image_decode_failed:lcd_requires_jpeg");
                return;
            }
            List<byte[]> pages = LcdEncoder.paginatePlusLcd(x, y, w, h, jpegBytes);
            session.writePages(pages);
            JSObject r = new JSObject();
            r.put("dropped", false);
            call.resolve(r);
        } catch (IllegalArgumentException e) {
            call.reject("image_oversized:" + e.getMessage());
        } catch (DeckSession.DeckIoException e) {
            call.reject(e.getMessage());
        } catch (Throwable t) {
            call.reject("lcd_write_failed:" + t.getMessage());
        }
    }
}
```

- [ ] **Step 2: Implement `StreamDeckPlugin`**

```java
package ca.erplibre.home.streamdeck;

import android.content.Context;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;
import android.util.Base64;
import android.util.Log;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.util.HashMap;
import java.util.Map;

import ca.erplibre.home.streamdeck.events.EventEmitter;
import ca.erplibre.home.streamdeck.usb.UsbHotplugReceiver;
import ca.erplibre.home.streamdeck.usb.UsbPermissionRequester;

/**
 * Capacitor plugin entry. Maintains one DeckSession per connected Stream Deck,
 * keyed by USB device name internally and exposed by serial number to JS.
 */
@CapacitorPlugin(name = "StreamDeckPlugin")
public class StreamDeckPlugin extends Plugin implements UsbHotplugReceiver.Listener {

    private static final String TAG = "StreamDeckPlugin";

    private UsbManager usb;
    private UsbHotplugReceiver hotplug;
    private UsbPermissionRequester permissions;

    /** Map keyed by USB device name (stable while plugged in). */
    private final Map<String, DeckSession> sessionsByDevice = new HashMap<>();
    /** Map keyed by serial number. Filled once the device is opened. */
    private final Map<String, DeckSession> sessionsBySerial = new HashMap<>();

    private final EventEmitter emitter = (name, data) -> notifyListeners(name, data);

    @Override
    public void load() {
        Context ctx = getContext();
        usb = (UsbManager) ctx.getSystemService(Context.USB_SERVICE);
        permissions = new UsbPermissionRequester(ctx, usb);
        hotplug = new UsbHotplugReceiver(this);
        hotplug.attach(ctx);
        scanExistingDevices();
    }

    @Override
    protected void handleOnDestroy() {
        if (hotplug != null) hotplug.detach(getContext());
        if (permissions != null) permissions.close();
        synchronized (sessionsByDevice) {
            for (DeckSession s : sessionsByDevice.values()) s.close("app_destroyed");
            sessionsByDevice.clear();
            sessionsBySerial.clear();
        }
    }

    private void scanExistingDevices() {
        for (UsbDevice d : usb.getDeviceList().values()) {
            if (!DeckRegistry.isElgato(d.getVendorId())) continue;
            onDeckAttached(d);
        }
    }

    @Override
    public void onDeckAttached(UsbDevice device) {
        DeckSpec spec = DeckRegistry.lookup(device.getProductId());
        if (spec == null) {
            Log.w(TAG, "unknown Elgato product 0x" + Integer.toHexString(device.getProductId()));
            return;
        }
        permissions.request(device).whenComplete((granted, err) -> {
            if (err != null || granted == null || !granted) {
                JSObject ev = new JSObject();
                ev.put("deckId", "");
                ev.put("reason", err != null ? err.getMessage() : "permission_denied");
                emitter.emit("permissionDenied", ev);
                return;
            }
            DeckSession session = new DeckSession(spec, device, emitter);
            try {
                session.open(usb);
                synchronized (sessionsByDevice) {
                    sessionsByDevice.put(device.getDeviceName(), session);
                    if (!session.serial().isEmpty()) {
                        sessionsBySerial.put(session.serial(), session);
                    }
                }
            } catch (DeckSession.DeckOpenException e) {
                JSObject ev = new JSObject();
                ev.put("deckId", "");
                ev.put("reason", e.getMessage());
                emitter.emit("permissionDenied", ev);
            }
        });
    }

    @Override
    public void onDeckDetached(UsbDevice device) {
        DeckSession session;
        synchronized (sessionsByDevice) {
            session = sessionsByDevice.remove(device.getDeviceName());
            if (session != null) sessionsBySerial.remove(session.serial());
        }
        if (session != null) session.close("usb_lost");
    }

    // ─────────────────────────── Plugin methods ──────────────────────────────

    @PluginMethod
    public void listDecks(PluginCall call) {
        JSArray arr = new JSArray();
        synchronized (sessionsByDevice) {
            for (DeckSession s : sessionsByDevice.values()) {
                arr.put(infoOf(s));
            }
        }
        JSObject r = new JSObject();
        r.put("decks", arr);
        call.resolve(r);
    }

    @PluginMethod
    public void getDeckInfo(PluginCall call) {
        DeckSession s = requireSession(call); if (s == null) return;
        call.resolve(infoOf(s));
    }

    @PluginMethod
    public void requestPermission(PluginCall call) {
        // Sessions are auto-opened on attach if permission was granted; this method
        // is a manual retry hook for the JS layer.
        DeckSession s = requireSession(call); if (s == null) return;
        JSObject r = new JSObject();
        r.put("granted", true);
        call.resolve(r);
    }

    @PluginMethod
    public void reset(PluginCall call) {
        DeckSession s = requireSession(call); if (s == null) return;
        try { s.reset(); call.resolve(); }
        catch (DeckSession.DeckIoException e) { call.reject(e.getMessage()); }
    }

    @PluginMethod
    public void setBrightness(PluginCall call) {
        DeckSession s = requireSession(call); if (s == null) return;
        int pct = call.getInt("percent", 50);
        try { s.setBrightness(pct); call.resolve(); }
        catch (DeckSession.DeckIoException e) { call.reject(e.getMessage()); }
    }

    @PluginMethod
    public void setKeyImage(PluginCall call) {
        DeckSession s = requireSession(call); if (s == null) return;
        Integer key = call.getInt("key");
        if (key == null || key < 0 || key >= s.spec().keyCount) {
            call.reject("invalid_key:" + key); return;
        }
        String b64 = call.getString("bytes");
        if (b64 == null) { call.reject("missing:bytes"); return; }
        byte[] raw;
        try { raw = Base64.decode(b64, Base64.NO_WRAP); }
        catch (IllegalArgumentException e) { call.reject("bad_base64"); return; }

        s.queue().offerCoalesce(new ImageWriteJob(s, key, raw, call));
        call.setKeepAlive(true); // resolved later from worker thread
    }

    @PluginMethod
    public void clearKey(PluginCall call) {
        DeckSession s = requireSession(call); if (s == null) return;
        Integer key = call.getInt("key");
        if (key == null) { call.reject("missing:key"); return; }
        // Encode a 1×1 black image in the model's expected format.
        byte[] black;
        if (s.spec().keyImageFormat == DeckSpec.ImageFormat.JPEG) {
            black = MINIMAL_BLACK_JPEG;
        } else {
            black = MINIMAL_BLACK_PNG;
        }
        s.queue().offerCoalesce(new ImageWriteJob(s, key, black, call));
        call.setKeepAlive(true);
    }

    @PluginMethod
    public void clearAllKeys(PluginCall call) {
        DeckSession s = requireSession(call); if (s == null) return;
        try { s.reset(); call.resolve(); }
        catch (DeckSession.DeckIoException e) { call.reject(e.getMessage()); }
    }

    @PluginMethod
    public void setLcdImage(PluginCall call) {
        DeckSession s = requireSession(call); if (s == null) return;
        if (s.spec().lcdW == 0) { call.reject("unsupported:no_lcd"); return; }
        byte[] raw = decodeBytes(call); if (raw == null) return;
        s.queue().offerCoalesce(new LcdWriteJob(
            s, 0, 0, s.spec().lcdW, s.spec().lcdH, raw, call, "lcd"));
        call.setKeepAlive(true);
    }

    @PluginMethod
    public void setLcdRegion(PluginCall call) {
        DeckSession s = requireSession(call); if (s == null) return;
        if (s.spec().lcdW == 0) { call.reject("unsupported:no_lcd"); return; }
        Integer x = call.getInt("x"); Integer y = call.getInt("y");
        Integer w = call.getInt("w"); Integer h = call.getInt("h");
        if (x == null || y == null || w == null || h == null) {
            call.reject("missing:x_y_w_h"); return;
        }
        byte[] raw = decodeBytes(call); if (raw == null) return;
        // Use a region-specific slot so different regions don't coalesce each other.
        String slot = "lcd:" + x + "," + y + "," + w + "," + h;
        s.queue().offerCoalesce(new LcdWriteJob(s, x, y, w, h, raw, call, slot));
        call.setKeepAlive(true);
    }

    @PluginMethod
    public void setInfoBar(PluginCall call) {
        // Neo info bars use a different command byte than Plus LCD. Wiring is
        // deferred to a separate plan once the protocol is cross-checked
        // against python-elgato-streamdeck StreamDeckNeo.py — see "Out of scope"
        // in this plan.
        call.reject("unsupported:neo_infobar_pending_protocol_verification");
    }

    private byte[] decodeBytes(PluginCall call) {
        String b64 = call.getString("bytes");
        if (b64 == null) { call.reject("missing:bytes"); return null; }
        try { return Base64.decode(b64, Base64.NO_WRAP); }
        catch (IllegalArgumentException e) { call.reject("bad_base64"); return null; }
    }

    // ──────────────────────────────── Helpers ────────────────────────────────

    private DeckSession requireSession(PluginCall call) {
        String id = call.getString("deckId");
        if (id == null) { call.reject("missing:deckId"); return null; }
        DeckSession s;
        synchronized (sessionsByDevice) { s = sessionsBySerial.get(id); }
        if (s == null) { call.reject("no_such_deck:" + id); return null; }
        return s;
    }

    private static JSObject infoOf(DeckSession s) {
        DeckSpec spec = s.spec();
        JSObject o = new JSObject();
        o.put("deckId", s.serial());
        o.put("model", spec.model);
        o.put("productId", spec.productId);
        o.put("rows", spec.rows);
        o.put("cols", spec.cols);
        o.put("keyCount", spec.keyCount);
        JSObject keyImg = new JSObject();
        keyImg.put("w", spec.keyImageW);
        keyImg.put("h", spec.keyImageH);
        keyImg.put("format", spec.keyImageFormat == DeckSpec.ImageFormat.JPEG ? "jpeg"
                          : spec.keyImageFormat == DeckSpec.ImageFormat.BMP_BGR_ROT180 ? "bmp_bgr_rot180"
                          : "bmp_bgr_rot270");
        o.put("keyImage", keyImg);
        o.put("dialCount", spec.dialCount);
        if (spec.lcdW > 0) {
            JSObject lcd = new JSObject();
            lcd.put("w", spec.lcdW); lcd.put("h", spec.lcdH);
            o.put("lcd", lcd);
        }
        if (spec.infoBarCount > 0) {
            JSObject ib = new JSObject();
            ib.put("w", spec.infoBarW); ib.put("h", spec.infoBarH); ib.put("count", spec.infoBarCount);
            o.put("infoBars", ib);
        }
        o.put("touchPoints", spec.touchPoints);
        o.put("firmwareVersion", s.firmware());
        JSArray caps = new JSArray();
        for (String c : spec.capabilities) caps.put(c);
        o.put("capabilities", caps);
        return o;
    }

    /** 8×8 single-pixel black JPEG, tiny placeholder. Generated once. */
    private static final byte[] MINIMAL_BLACK_JPEG = Base64.decode(
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
        + "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB/9sAQwEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
        + "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAA"
        + "AAAAAAAAAAAAAAr/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEA"
        + "AAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwA/AAH/2Q==", Base64.NO_WRAP);

    /** 1×1 black PNG. */
    private static final byte[] MINIMAL_BLACK_PNG = Base64.decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        Base64.NO_WRAP);
}
```

- [ ] **Step 3: Verify compile**

Run: `cd android && ./gradlew :app:compileDebugJavaWithJavac`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 4: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/streamdeck/StreamDeckPlugin.java \
        android/app/src/main/java/ca/erplibre/home/streamdeck/ImageWriteJob.java \
        android/app/src/main/java/ca/erplibre/home/streamdeck/LcdWriteJob.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: StreamDeckPlugin entry + Image/LcdWriteJob"
```

---

## Task 16: Register the plugin in `MainActivity`

**Files:**
- Modify: `android/app/src/main/java/ca/erplibre/home/MainActivity.java`

- [ ] **Step 1: Add the import and the registerPlugin line**

Add the import near the existing imports:

```java
import ca.erplibre.home.streamdeck.StreamDeckPlugin;
```

Add the `registerPlugin` call inside `onCreate`, alongside the other six existing `registerPlugin(...)` calls:

```java
        registerPlugin(StreamDeckPlugin.class);
```

- [ ] **Step 2: Verify build**

Run: `cd android && ./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 3: Commit**

```bash
cd mobile/erplibre_home_mobile
git add android/app/src/main/java/ca/erplibre/home/MainActivity.java
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: register StreamDeckPlugin in MainActivity"
```

---

## Task 17: TypeScript bridge (`streamDeckPlugin.ts`)

**Files:**
- Create: `src/plugins/streamDeckPlugin.ts`

- [ ] **Step 1: Create the file with the typed bridge**

```typescript
import { registerPlugin } from "@capacitor/core";
import type { PluginListenerHandle } from "@capacitor/core";

export type DeckModel =
    | "original_v1"
    | "original_v2"
    | "mini"
    | "mk2"
    | "xl"
    | "plus"
    | "neo";

export type DeckImageFormat = "jpeg" | "bmp_bgr_rot180" | "bmp_bgr_rot270";

export interface DeckInfo {
    deckId: string;
    model: DeckModel;
    productId: number;
    rows: number;
    cols: number;
    keyCount: number;
    keyImage: { w: number; h: number; format: DeckImageFormat };
    dialCount: number;
    lcd?: { w: number; h: number };
    infoBars?: { w: number; h: number; count: number };
    touchPoints: number;
    firmwareVersion: string;
    capabilities: string[];
}

export interface KeyEvent {
    deckId: string;
    key: number;
    pressed: boolean;
}

export interface DialRotateEvent {
    deckId: string;
    dial: number;
    delta: number;
}

export interface DialPressEvent {
    deckId: string;
    dial: number;
    pressed: boolean;
}

export interface LcdTouchEvent {
    deckId: string;
    type: "short" | "long" | "drag";
    x: number;
    y: number;
    xEnd?: number;
    yEnd?: number;
}

export interface NeoTouchEvent {
    deckId: string;
    index: number;
    pressed: boolean;
}

export interface DeckLifecycleEvent {
    deckId: string;
    info?: DeckInfo;
    reason?: string;
}

export interface ImageWriteResult {
    dropped?: boolean;
}

interface StreamDeckPluginApi {
    listDecks(): Promise<{ decks: DeckInfo[] }>;
    getDeckInfo(opts: { deckId: string }): Promise<DeckInfo>;
    requestPermission(opts: { deckId: string }): Promise<{ granted: boolean }>;
    reset(opts: { deckId: string }): Promise<void>;
    setBrightness(opts: { deckId: string; percent: number }): Promise<void>;

    setKeyImage(opts: {
        deckId: string;
        key: number;
        bytes: string; // base64
        format: "jpeg" | "png";
    }): Promise<ImageWriteResult>;
    clearKey(opts: { deckId: string; key: number }): Promise<ImageWriteResult>;
    clearAllKeys(opts: { deckId: string }): Promise<void>;

    setLcdImage(opts: { deckId: string; bytes: string }): Promise<ImageWriteResult>;
    setLcdRegion(opts: {
        deckId: string;
        x: number;
        y: number;
        w: number;
        h: number;
        bytes: string;
    }): Promise<ImageWriteResult>;
    setInfoBar(opts: { deckId: string; index: 0 | 1; bytes: string }): Promise<ImageWriteResult>;

    addListener(
        eventName: "deckConnected",
        listener: (ev: DeckLifecycleEvent) => void
    ): Promise<PluginListenerHandle>;
    addListener(
        eventName: "deckDisconnected",
        listener: (ev: DeckLifecycleEvent) => void
    ): Promise<PluginListenerHandle>;
    addListener(
        eventName: "permissionDenied",
        listener: (ev: DeckLifecycleEvent) => void
    ): Promise<PluginListenerHandle>;
    addListener(
        eventName: "keyChanged",
        listener: (ev: KeyEvent) => void
    ): Promise<PluginListenerHandle>;
    addListener(
        eventName: "dialRotated",
        listener: (ev: DialRotateEvent) => void
    ): Promise<PluginListenerHandle>;
    addListener(
        eventName: "dialPressed",
        listener: (ev: DialPressEvent) => void
    ): Promise<PluginListenerHandle>;
    addListener(
        eventName: "lcdTouched",
        listener: (ev: LcdTouchEvent) => void
    ): Promise<PluginListenerHandle>;
    addListener(
        eventName: "neoTouched",
        listener: (ev: NeoTouchEvent) => void
    ): Promise<PluginListenerHandle>;
}

export const StreamDeckPlugin = registerPlugin<StreamDeckPluginApi>("StreamDeckPlugin");
```

- [ ] **Step 2: Verify TS compiles**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd mobile/erplibre_home_mobile
git add src/plugins/streamDeckPlugin.ts
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: TypeScript bridge for StreamDeckPlugin"
```

---

## Task 18: Vitest TS bridge tests

**Files:**
- Create: `src/__tests__/streamDeckPlugin.test.ts`

- [ ] **Step 1: Write the failing test (uses the existing Capacitor mock pattern from `networkScanPlugin.test.ts`)**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";

const mockListDecks = vi.fn();
const mockSetKeyImage = vi.fn();
const mockAddListener = vi.fn();

vi.mock("@capacitor/core", () => ({
    registerPlugin: () => ({
        listDecks: mockListDecks,
        setKeyImage: mockSetKeyImage,
        addListener: mockAddListener,
    }),
}));

import { StreamDeckPlugin, DeckInfo } from "../plugins/streamDeckPlugin";

describe("StreamDeckPlugin TS bridge", () => {
    beforeEach(() => {
        mockListDecks.mockReset();
        mockSetKeyImage.mockReset();
        mockAddListener.mockReset();
    });

    it("listDecks returns typed DeckInfo array", async () => {
        const sample: DeckInfo = {
            deckId: "AL01",
            model: "mk2",
            productId: 0x0080,
            rows: 3,
            cols: 5,
            keyCount: 15,
            keyImage: { w: 72, h: 72, format: "jpeg" },
            dialCount: 0,
            touchPoints: 0,
            firmwareVersion: "1.0",
            capabilities: ["keys"],
        };
        mockListDecks.mockResolvedValue({ decks: [sample] });
        const r = await StreamDeckPlugin.listDecks();
        expect(r.decks).toHaveLength(1);
        expect(r.decks[0].model).toBe("mk2");
        expect(r.decks[0].keyCount).toBe(15);
    });

    it("setKeyImage forwards base64 + format to native", async () => {
        mockSetKeyImage.mockResolvedValue({ dropped: false });
        const r = await StreamDeckPlugin.setKeyImage({
            deckId: "AL01",
            key: 3,
            bytes: "QkFTRTY0",
            format: "jpeg",
        });
        expect(r.dropped).toBe(false);
        expect(mockSetKeyImage).toHaveBeenCalledWith({
            deckId: "AL01",
            key: 3,
            bytes: "QkFTRTY0",
            format: "jpeg",
        });
    });

    it("setKeyImage surfaces dropped=true when coalesced", async () => {
        mockSetKeyImage.mockResolvedValue({ dropped: true });
        const r = await StreamDeckPlugin.setKeyImage({
            deckId: "AL01", key: 0, bytes: "AA==", format: "jpeg",
        });
        expect(r.dropped).toBe(true);
    });

    it("addListener wires keyChanged events", async () => {
        const handler = vi.fn();
        mockAddListener.mockResolvedValue({ remove: vi.fn() });
        await StreamDeckPlugin.addListener("keyChanged", handler);
        expect(mockAddListener).toHaveBeenCalledWith("keyChanged", handler);
    });
});
```

- [ ] **Step 2: Run, confirm fail (no test file yet — but the file exists now, so this should already run)**

Run: `npm test -- streamDeckPlugin`
Expected: 4 tests pass.

If a test fails because of an actual bridge bug, fix the bridge in `src/plugins/streamDeckPlugin.ts`.

- [ ] **Step 3: Commit**

```bash
cd mobile/erplibre_home_mobile
git add src/__tests__/streamDeckPlugin.test.ts
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: vitest tests for TS bridge"
```

---

## Task 19: Manual hardware test matrix doc

**Files:**
- Create: `mobile/erplibre_home_mobile/doc/streamdeck_test_matrix.md`

- [ ] **Step 1: Create the doc**

```markdown
# Stream Deck Mobile — Hardware Test Matrix

These checks must be run by hand against each physical device before a release.
There is no CI runner with hardware, so this is the safety net.

## Setup

- USB OTG cable or powered hub plugged into the device under test.
- Build install: `npm run build && npx cap sync android && cd android && ./gradlew installDebug`
- A running ERPLibre Home Mobile build with `StreamDeckPlugin` registered.

## Checklist (per physical deck)

For each of: Original v1, Mini, Original v2, MK.2, XL, Plus, Neo.

- [ ] Plug deck in with app **closed**. App should launch via the USB
      ATTACHED intent-filter and show the deck in `listDecks()`.
- [ ] Plug deck in with app **open**. Permission dialog should appear,
      grant; deck appears in `listDecks()` within 1s.
- [ ] `setBrightness` 0, 50, 100 — visible difference at each level.
- [ ] `setKeyImage` with the chequerboard test pattern (red/blue, key
      index drawn on top) for every key. Visual check: every key shows
      its index in the right place.
- [ ] Press every key once — `keyChanged {pressed:true}` then
      `{pressed:false}` reported with correct key index.
- [ ] (Plus only) Rotate each dial ±5 ticks — `dialRotated` events with
      correct sign.
- [ ] (Plus only) Press each dial — `dialPressed` true/false events.
- [ ] (Plus only) Tap, long-press, and drag on LCD — `lcdTouched`
      events with type and coordinates.
- [ ] (Neo only) Tap each capacitive touch point — `neoTouched` events
      with correct index.
- [ ] `reset` clears all images.
- [ ] Unplug deck — `deckDisconnected` fires within ~500ms.
- [ ] Replug — `deckConnected` fires; `deckId` (serial) is the same as before.
```

- [ ] **Step 2: Commit**

```bash
cd mobile/erplibre_home_mobile
git add doc/streamdeck_test_matrix.md
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: manual hardware test matrix"
```

---

## Task 20: Update `doc/NATIVE_PLUGINS.md`

**Files:**
- Modify: `mobile/erplibre_home_mobile/doc/NATIVE_PLUGINS.md`

- [ ] **Step 1: Append a new section following the existing format**

After the last existing plugin section (`DeviceStatsPlugin`), append:

````markdown

---

## StreamDeckPlugin

**Fichiers :**
- Bridge TS : `src/plugins/streamDeckPlugin.ts`
- Implémentation Java : `android/app/src/main/java/ca/erplibre/home/streamdeck/`
- Filtre USB : `android/app/src/main/res/xml/streamdeck_devices.xml`

**Bibliothèque :** Android USB Host API natif (`UsbManager`, `UsbDeviceConnection`, `bulkTransfer`, `controlTransfer`).

**Modèles supportés :** Elgato Stream Deck Original v1 (`0x0060`), Mini
(`0x0063`), XL (`0x006c`), Original v2 (`0x006d`), MK.2 (`0x0080`),
Plus (`0x0084`), Neo (`0x009a`). Vendor `0x0fd9`.

### API

| Méthode | Description |
|---------|-------------|
| `listDecks()` | Retourne tous les decks connus, chacun avec capacités (keys/dials/lcd/infobars/touchpoints). |
| `getDeckInfo({deckId})` | Détail d'un deck (model, rows/cols, keyImage, dials, lcd…). |
| `requestPermission({deckId})` | Force la demande de permission USB si manquante. |
| `reset({deckId})` | Efface toutes les images des touches. |
| `setBrightness({deckId, percent})` | Luminosité 0..100. |
| `setKeyImage({deckId, key, bytes, format})` | Pousse une image. `bytes` = base64. `format = "jpeg"` pour v2+/MK.2/XL/Plus/Neo, `"png"` pour v1/Mini (Java fait BMP rotaté). Résout `{dropped: true}` si une image plus récente a été poussée pour la même touche entre-temps. |
| `clearKey({deckId, key})` | Image noire 1×1 → touche éteinte. |
| `clearAllKeys({deckId})` | Identique à `reset`. |
| `setLcdImage({deckId, bytes})` | Plus uniquement — JPEG plein 800×100. |
| `setLcdRegion({deckId, x, y, w, h, bytes})` | Plus uniquement — JPEG région partielle. |
| `setInfoBar({deckId, index, bytes})` | Neo uniquement — **non implémenté** dans ce plan, rejette `unsupported:neo_infobar_pending_protocol_verification`. À compléter dans un plan ultérieur après vérification du protocole Neo. |

### Events

| Event | Payload |
|-------|---------|
| `deckConnected` | `{deckId, info, reason?}` |
| `deckDisconnected` | `{deckId, reason}` (`usb_lost`, `app_destroyed`) |
| `permissionDenied` | `{deckId, reason}` |
| `keyChanged` | `{deckId, key, pressed}` |
| `dialRotated` | `{deckId, dial, delta}` (Plus) |
| `dialPressed` | `{deckId, dial, pressed}` (Plus) |
| `lcdTouched` | `{deckId, type, x, y, xEnd?, yEnd?}` (Plus) |
| `neoTouched` | `{deckId, index, pressed}` (Neo) |

### Identité persistante

Les decks sont identifiés par leur **numéro de série USB** (lu via
feature report à la connexion). Un deck rebranché conserve donc son
`deckId` — les préférences/layouts/snapshots peuvent être indexés par
ce serial sans risque.

### Architecture

Pattern strategy. `DeckRegistry` mappe `productId → DeckSpec`. Une
`DeckSession` par deck connecté possède son propre thread reader (HID
IN), thread writer (HID OUT consommant `WriterQueue`), et un
`DeckTransport` + `ImageEncoder` choisis selon la spec. Les images
poussées rapidement pour la même touche sont coalescées : la dernière
gagne, les plus anciennes résolvent leur Promise avec `{dropped: true}`.

### Tests manuels

Voir `doc/streamdeck_test_matrix.md` — checklist par modèle physique.
````

- [ ] **Step 2: Commit**

```bash
cd mobile/erplibre_home_mobile
git add doc/NATIVE_PLUGINS.md
git -c commit.gpgsign=false commit -m "[ADD] streamdeck_mobile: document plugin in NATIVE_PLUGINS.md"
```

---

## Final Validation

- [ ] **Step 1: All Java unit tests green**

Run: `cd mobile/erplibre_home_mobile/android && ./gradlew :app:testDebugUnitTest`
Expected: BUILD SUCCESSFUL with 5 test classes (`DeckRegistryTest`, `RgbaRotatorTest`, `TransportV1Test`, `TransportV2Test`, `WriterQueueTest`, `LcdEncoderTest`).

- [ ] **Step 2: Vitest green**

Run: `cd mobile/erplibre_home_mobile && npm test`
Expected: BUILD SUCCESSFUL including the new `streamDeckPlugin.test.ts`.

- [ ] **Step 3: Debug APK builds**

Run: `cd mobile/erplibre_home_mobile/android && ./gradlew :app:assembleDebug`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 4: Hardware matrix run**

Follow `doc/streamdeck_test_matrix.md` for each physical deck available.

- [ ] **Step 5: Hand off to sub-project #2**

The plugin is now consumable by sub-project #2 (Stream Deck service in
`src/services/streamDeckService.ts`). The follow-up plan should be
brainstormed + written separately.

---

## Notes for the executing engineer

- **Do not invent protocol bytes.** Every transport/encoder/parser
  constant must be cross-checked against
  [`python-elgato-streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck/tree/master/src/StreamDeck/Devices)
  before committing. The values in this plan are best-effort from
  spec memory and may need adjustment per model. Tests assert
  structural properties (page sizes, last-flag, header byte patterns)
  rather than exact full-page byte equality, which keeps the test
  suite stable while you correct any drift.
- **Bitmap-dependent code is not unit-tested.** `BmpEncoder`,
  `JpegEncoder` magic-byte checks, and the Capacitor plugin layer all
  depend on Android APIs. They are validated by the manual hardware
  matrix in Task 19.
- **Keep PR-able commits small.** The TDD steps in each task already
  give a one-task-one-commit cadence. Don't fold tasks together.
- **Follow-up sub-projects** (#2 service, #3 BluetoothPlugin, #4
  controller port) are out of scope here. Open separate
  brainstorms for each before writing implementation plans.
- **Neo info bars** (`setInfoBar`) are out of scope in this plan.
  The plugin rejects the call with
  `unsupported:neo_infobar_pending_protocol_verification`. A small
  follow-up plan should add the Neo command-byte pagination once
  `python-elgato-streamdeck/src/StreamDeck/Devices/StreamDeckNeo.py`
  has been read and the values confirmed; the rest of the plumbing
  (event emit, manifest, lifecycle) is already in place here.
