// Pont de la fenêtre bureautique, sans OWL ni DOM. Dans la fenêtre
// pywebview, `window.pywebview.api` porte les trois méthodes du pont,
// `set_title`, `notify` et `pick_path` ; pywebview l'injecte une fois la
// page chargée et le dit par l'évènement `pywebviewready`. Dans un
// navigateur, il n'existe jamais : rien ne part, et la page ne change rien
// d'autre.

// Secondes au-delà desquelles la fin d'une commande se notifie.
export const LONG_RUN = 10;

// Nom, dans le fragment de l'URL, du jeton que la fenêtre tire pour son
// pont, et sa clé dans le sessionStorage.
export const TOKEN = "bridge";
const TOKEN_KEY = "todo_web.bridge";

// Jeton du pont pour la page de `win` : le premier que garde le
// sessionStorage de `win`, propre à l'origine du hub et à la fenêtre, sinon
// celui du fragment `fragment` (URLSearchParams), qui y est alors gardé. Le
// jeton est retiré de `fragment` dans tous les cas. Le lien d'ouverture de
// la fenêtre le porte ; un rechargement, ou le retour au hub après une page
// étrangère, le relisent du stockage ; un lien vers le hub qui en porterait
// un autre ne le remplace pas. null sans jeton, dans un navigateur par
// exemple ; un stockage refusé garde celui du fragment pour cette page.
export function takeToken(win, fragment) {
    const given = fragment.get(TOKEN) || null;
    fragment.delete(TOKEN);
    try {
        const kept = win.sessionStorage.getItem(TOKEN_KEY);
        if (kept) {
            return kept;
        }
        if (given) {
            win.sessionStorage.setItem(TOKEN_KEY, given);
        }
    } catch {
        // Stockage refusé : le jeton du fragment vaut pour cette page.
    }
    return given;
}

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

// Pont de la page `win` (son objet `window`), de titre de départ `base` et
// de jeton `token` (`takeToken`). `title(crumbs)` règle le titre de la
// fenêtre, s'il change ; `notify(body)` envoie une notification titrée
// comme la fenêtre ; `canPick()` dit si la fenêtre offre le dialogue de
// fichiers du système, que `pickPath(start, directory)` ouvre, et dont il
// rend le chemin choisi, ou null : renoncé, refusé, hors de la fenêtre ou
// en échec. Chaque appel porte d'abord `token`, que le pont exige ;
// sans jeton, rien ne part. Seule une méthode que l'API porte est appelée ;
// son erreur, ou sa promesse rejetée, est ignorée : un titre ou une
// notification perdus n'arrêtent pas la page. Le titre courant part aussi
// à chaque `pywebviewready`, qui suit l'injection de l'API, rechargement
// compris. Dans la fenêtre, un lien ou un fichier déposé est refusé : le
// moteur y chargerait une autre page.
export function desktopBridge(win, base, token) {
    const refuse = (event) => win.pywebview && event.preventDefault();
    win.addEventListener("dragover", refuse);
    win.addEventListener("drop", refuse);
    let current = base;
    const call = (name, ...args) => {
        const api = win.pywebview?.api;
        if (!token || typeof api?.[name] !== "function") {
            return;
        }
        try {
            Promise.resolve(api[name](token, ...args)).catch(() => {});
        } catch {
            // L'API a levé sans promesse : rien de plus à faire.
        }
    };
    const ready = () => call("set_title", current);
    win.addEventListener("pywebviewready", ready);
    ready();
    const canPick = () => Boolean(token) && typeof win.pywebview?.api?.pick_path === "function";
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
        canPick,
        async pickPath(start, directory) {
            if (!canPick()) {
                return null;
            }
            try {
                const chosen = await win.pywebview.api.pick_path(token, start, directory);
                return typeof chosen === "string" && chosen ? chosen : null;
            } catch {
                return null;
            }
        },
    };
}
