/**
 * USB helpers — parse `lsusb -d 0fd9: -v` output to detect Elgato Stream Deck
 * devices. Pure parser is testable under Node; GJS dispatcher invokes lsusb.
 */

const HEADER_RE =
    /^Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-f]{4}):([0-9a-f]{4})\s+(.*)$/;

export function parseLsusbVerbose(text) {
    if (typeof text !== 'string' || text === '') return [];
    const out = [];
    let cur = null;
    for (const line of text.split('\n')) {
        const h = line.match(HEADER_RE);
        if (h) {
            if (cur) out.push(cur);
            cur = {
                bus: h[1], device: h[2],
                vendor_id: h[3], product_id: h[4],
                vendor_name: h[5].trim(),
                product: '', serial: '', manufacturer: '',
            };
            continue;
        }
        if (!cur) continue;
        const t = line.trim();
        const grab = (label) => {
            const r = new RegExp(`^${label}\\s+\\d+\\s+(.+)$`);
            const m = t.match(r);
            return m ? m[1].trim() : null;
        };
        const prod = grab('iProduct');
        if (prod !== null) cur.product = prod;
        const ser = grab('iSerial');
        if (ser !== null) cur.serial = ser;
        const man = grab('iManufacturer');
        if (man !== null) cur.manufacturer = man;
    }
    if (cur) out.push(cur);
    return out;
}

/**
 * GJS-only — run lsusb -d 0fd9: -v and parse.
 */
export async function detectStreamDecksGjs() {
    const {default: GLib} = await import('gi://GLib');
    if (!GLib.find_program_in_path('lsusb')) return [];
    const [, stdout] = GLib.spawn_command_line_sync('lsusb -d 0fd9: -v');
    return parseLsusbVerbose(
        new TextDecoder().decode(stdout || new Uint8Array()));
}
