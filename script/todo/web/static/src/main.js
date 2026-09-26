// Amorçage de la page. Le fragment de l'URL porte « login » (code à usage
// unique), « view » et « lang » : le code en est retiré avant tout appel
// réseau et ne reste ni dans l'historique ni dans un rechargement. Puis la
// session donne le jeton CSRF et la langue par défaut, et la page charge la
// table de traduction et la télémétrie avant de monter la vue.
import {mount} from "@odoo/owl";
import {ApiError, getJson, postJson, setCsrfToken} from "./api.js";
import {TelemetryPage} from "./tree_view.js";

const LANGUAGES = ["fr", "en"];
// Sans session, aucune table de traduction n'est lisible : ces messages
// restent en anglais.
const EXPIRED = "This link has expired or was already used: open the page again from TODO.";
const FAILED = "The TODO web interface did not answer.";

function takeFragment() {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const code = fragment.get("login");
    if (code) {
        fragment.delete("login");
        const rest = fragment.toString();
        history.replaceState(null, "", rest ? `#${rest}` : window.location.pathname);
    }
    return {code, lang: fragment.get("lang")};
}

function showError(message) {
    const box = document.createElement("p");
    box.className = "error";
    box.textContent = message;
    document.getElementById("app").replaceChildren(box);
}

async function start() {
    const {code, lang} = takeFragment();
    if (code) {
        try {
            await postJson("/api/login", {code});
        } catch (error) {
            // Un code refusé n'arrête rien si le cookie d'une connexion
            // précédente est encore valide : /api/session tranche.
            if (!(error instanceof ApiError)) {
                throw error;
            }
        }
    }
    const session = await getJson("/api/session");
    setCsrfToken(session.csrf);
    const chosen = LANGUAGES.includes(lang) ? lang : session.lang;
    document.documentElement.lang = chosen;
    const [terms, telemetry] = await Promise.all([
        getJson(`/api/i18n?lang=${chosen}`),
        getJson(`/api/telemetry?lang=${chosen}`),
    ]);
    await mount(TelemetryPage, document.getElementById("app"), {
        props: {root: session.root, telemetry, terms},
    });
}

start().catch((error) => {
    showError(error instanceof ApiError && error.status === 403 ? EXPIRED : FAILED);
});
