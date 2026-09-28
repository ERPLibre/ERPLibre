// Pont de la fenêtre bureautique, sans OWL ni DOM. Dans la fenêtre
// pywebview, `window.pywebview.api` porte les deux méthodes du pont,
// `set_title` et `notify` ; pywebview l'injecte une fois la page chargée et
// le dit par l'évènement `pywebviewready`. Dans un navigateur, il n'existe
// jamais : rien ne part, et la page ne change rien d'autre.

// Secondes au-delà desquelles la fin d'une commande se notifie.
export const LONG_RUN = 10;

// Titre de la fenêtre : le fil d'Ariane `crumbs`, puis `base` ; `base`
// seul sans fil.
export function windowTitle(base, crumbs) {
    return crumbs?.length ? `${crumbs.join(" › ")} — ${base}` : base;
}

// Vrai pour la fin (`run_end`) d'une commande de plus de LONG_RUN secondes.
export function endsLongRun(message) {
    return message.t === "run_end" && Number(message.secs) > LONG_RUN;
}

// Corps de la notification d'une fin de commande `run_end` : son code de
// sortie, « — » pour une commande interrompue, et sa durée arrondie.
export function runEndBody(t, message) {
    const rc = message.rc ?? "—";
    return t("Command ended: exit code %s, %s s").replace("%s", rc).replace("%s", Math.round(message.secs));
}

// Pont de la page `win` (son objet `window`), de titre de départ `base`.
// `title(crumbs)` règle le titre de la fenêtre, s'il change ; `notify(body)`
// envoie une notification titrée comme la fenêtre. Seule une méthode que
// l'API porte est appelée ; son erreur, ou sa promesse rejetée, est
// ignorée : un titre ou une notification perdus n'arrêtent pas la page.
// Le titre courant part aussi à chaque `pywebviewready`, qui suit
// l'injection de l'API, rechargement compris. Dans la fenêtre, un lien ou
// un fichier déposé est refusé : le moteur y chargerait une autre page.
export function desktopBridge(win, base) {
    const refuse = (event) => win.pywebview && event.preventDefault();
    win.addEventListener("dragover", refuse);
    win.addEventListener("drop", refuse);
    let current = base;
    const call = (name, ...args) => {
        const api = win.pywebview?.api;
        if (typeof api?.[name] !== "function") {
            return;
        }
        try {
            Promise.resolve(api[name](...args)).catch(() => {});
        } catch {
            // L'API a levé sans promesse : rien de plus à faire.
        }
    };
    const ready = () => call("set_title", current);
    win.addEventListener("pywebviewready", ready);
    ready();
    return {
        title(crumbs) {
            const text = windowTitle(base, crumbs);
            if (text !== current) {
                current = text;
                call("set_title", text);
            }
        },
        notify(body) {
            call("notify", current, body);
        },
    };
}
