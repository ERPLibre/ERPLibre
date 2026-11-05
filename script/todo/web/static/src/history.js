// Ce que montre la vue Historique, sans OWL ni DOM : une tâche de
// /api/tasks ({id, crumbs, entry, start, end, state, commands, lines}) et un
// enregistrement de son journal ({n, t, s, d}) mis en texte. `t` est la
// table de traduction de la page.

// Fil d'Ariane de la tâche, jusqu'à l'entrée choisie.
export function taskTitle(task) {
    return [...(task.crumbs || []), task.entry].filter(Boolean).join(" › ");
}

// Code de retour : celui de la première commande qui n'a pas rendu 0, « ? »
// pour une commande interrompue, 0 si toutes ont réussi, "" sans commande.
export function taskRc(task) {
    const commands = task.commands || [];
    const failed = commands.find((command) => command.rc !== 0);
    if (failed) {
        return failed.rc ?? "?";
    }
    return commands.length ? 0 : "";
}

// Première commande, suivie du nombre des autres.
export function taskCommands(task) {
    const commands = task.commands || [];
    if (!commands.length) {
        return "";
    }
    const others = commands.length > 1 ? ` (+${commands.length - 1})` : "";
    return commands[0].cmd + others;
}

// Durée en secondes, arrondie : « 42 s », « 3 min 05 s », « 2 h 07 min » ;
// "" pour ce qui n'en est pas une.
export function duration(seconds) {
    if (typeof seconds !== "number" || !(seconds >= 0)) {
        return "";
    }
    const s = Math.round(seconds);
    const pad = (n) => String(n).padStart(2, "0");
    if (s < 60) {
        return `${s} s`;
    }
    if (s < 3600) {
        return `${Math.floor(s / 60)} min ${pad(s % 60)} s`;
    }
    return `${Math.floor(s / 3600)} h ${pad(Math.floor((s % 3600) / 60))} min`;
}

// État d'une tâche, traduit ; une session finie avant la tâche en dernier.
export function stateLabel(state, t) {
    const labels = {done: t("done"), interrupted: t("interrupted"), open: t("running")};
    return labels[state] ?? t("Session ended");
}

// Une ligne de texte par enregistrement : la sortie telle quelle, un
// événement résumé. La vue l'affiche par t-esc, jamais comme du HTML.
export function recordText(record, t) {
    const d = record.d;
    if (record.s === "out") {
        return String(d);
    }
    switch (d.t) {
        case "task_start":
            return `▶ ${taskTitle(d)}`;
        case "run_start":
            return `$ ${d.cmd}`;
        case "run_end":
            return `⏎ ${t("Exit code")} ${d.rc ?? "?"} · ${duration(d.secs)}`;
        case "ask":
            return `? ${d.text}`;
        case "answer":
            return `→ ${d.value}`;
        case "answered":
            return `→ (${t("answered in the terminal")})`;
        case "cancel":
            return `✕ ${t("cancelled")}`;
        case "timeout":
            return `⏱ ${t("timed out")}`;
        case "notice":
            return `! ${d.text}`;
        case "omitted":
            return `… ${d.bytes} ${t("bytes omitted")}`;
        default:
            return JSON.stringify(d);
    }
}
