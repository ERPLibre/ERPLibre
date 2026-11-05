// Mise en forme du relevé de /api/system pour la vue Système, sans OWL ni
// DOM. Les unités viennent d'Intl dans la langue de la page : aucune clé de
// traduction pour « Go » ou « GB ».

// Octets en unités décimales (ko, Mo, Go… selon `lang`), par seconde si
// `rate`.
export function formatBytes(bytes, lang, rate = false) {
    const units = ["byte", "kilobyte", "megabyte", "gigabyte", "terabyte"];
    let value = bytes;
    let rank = 0;
    while (value >= 1000 && rank < units.length - 1) {
        value /= 1000;
        rank += 1;
    }
    const unit = rate ? `${units[rank]}-per-second` : units[rank];
    return new Intl.NumberFormat(lang, {style: "unit", unit, maximumFractionDigits: 1}).format(value);
}

function formatUnit(value, unit, lang) {
    return new Intl.NumberFormat(lang, {style: "unit", unit, unitDisplay: "narrow"}).format(value);
}

// Durée en jours et heures, heures et minutes, ou minutes.
export function formatDuration(seconds, lang) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days) {
        return `${formatUnit(days, "day", lang)} ${formatUnit(hours, "hour", lang)}`;
    }
    if (hours) {
        return `${formatUnit(hours, "hour", lang)} ${formatUnit(minutes, "minute", lang)}`;
    }
    return formatUnit(minutes, "minute", lang);
}

// Lignes de la vue Système : [libellé, valeur, part de 0 à 1 ou null].
// `metrics` est celui de /api/system ; `temp`, le dernier relevé de
// température reçu ([source, [°C…]] ou null). Une mesure absente de la
// machine n'a pas de ligne ; le processeur et le réseau, qui demandent deux
// relevés, montrent « … » au premier.
export function systemRows(metrics, temp, t, lang) {
    const number = (value, digits) => new Intl.NumberFormat(lang, {maximumFractionDigits: digits}).format(value);
    const percent = (ratio) => new Intl.NumberFormat(lang, {style: "percent"}).format(ratio);
    const rows = [];
    const state = [`${t("uptime")} ${metrics.uptime === null ? "…" : formatDuration(metrics.uptime, lang)}`];
    if (metrics.load) {
        state.push(`${t("load")} ${metrics.load.map((value) => number(value, 1)).join(" / ")}`);
    }
    rows.push([t("State"), state.join(" · "), null]);
    const cpu = metrics.cpu === null ? "…" : percent(metrics.cpu / 100);
    rows.push([t("CPU"), `${cpu} · ${metrics.ncpu} ${t("cores")}`, metrics.cpu === null ? null : metrics.cpu / 100]);
    if (metrics.mem) {
        const [total, used] = metrics.mem;
        const share = total ? used / total : 0;
        rows.push([t("Memory"), `${formatBytes(used, lang)} / ${formatBytes(total, lang)} · ${percent(share)}`, share]);
    }
    if (metrics.disk) {
        const [total, used, free] = metrics.disk;
        const share = total ? used / total : 0;
        const text = `${formatBytes(used, lang)} / ${formatBytes(total, lang)} · ${percent(share)}`;
        rows.push([`${t("Disk")} /`, `${text} · ${formatBytes(free, lang)} ${t("free")}`, share]);
    }
    if (metrics.net) {
        const [down, up] = metrics.net.map((rate) => formatBytes(rate, lang, true));
        rows.push([t("Network"), `↓ ${down} · ↑ ${up}`, null]);
    } else {
        rows.push([t("Network"), "…", null]);
    }
    if (metrics.battery) {
        const [capacity, status] = metrics.battery;
        const text = status ? `${percent(capacity / 100)} (${status})` : percent(capacity / 100);
        rows.push([t("Battery"), text, capacity / 100]);
    }
    const hottest = temp ? Math.max(...temp[1]) : null;
    const celsius = new Intl.NumberFormat(lang, {style: "unit", unit: "celsius", maximumFractionDigits: 0});
    rows.push([t("Temperature"), temp ? `${celsius.format(hottest)} (${t("max")})` : t("unavailable"), null]);
    return rows;
}
