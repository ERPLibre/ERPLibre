// Amorçage de la page. Le fragment de l'URL porte « login » (code à usage
// unique), « view » et « lang » : le code en est retiré avant tout appel
// réseau, il quitte donc la barre d'adresse et un rechargement ne le retrouve
// pas. L'historique du navigateur peut garder l'URL d'arrivée, code compris :
// un code déjà dépensé par la connexion qui suit, ou périmé après 120 s.
// Puis la session donne le jeton CSRF et la langue par défaut, et la page
// charge la table de traduction et la télémétrie avant de monter la vue.
import {mount} from "@odoo/owl";
import {ApiError, getJson, postJson, setCsrfToken} from "./api.js";
import {TelemetryPage} from "./telemetry_page.js";

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
    // `env` est partagé par tous les composants : la table de traduction, la
    // langue, qui règle aussi le tri par nom et les unités, et le jeton CSRF,
    // que le premier message d'un WebSocket porte.
    const t = (key) => terms[key] ?? key;
    await mount(TelemetryPage, document.getElementById("app"), {
        env: {t, lang: chosen, csrf: session.csrf},
        props: {root: session.root, telemetry},
    });
}

start().catch((error) => {
    showError(error instanceof ApiError && error.status === 403 ? EXPIRED : FAILED);
});
