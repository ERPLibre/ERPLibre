// Lancer un nœud de l'arbre de télémétrie, sans OWL ni DOM : dans une
// session, répondre à chaque menu l'entrée dont le libellé est l'étape
// suivante du chemin, comme l'utilisateur le ferait. Un nœud est celui de
// /api/telemetry : {key, label, entry, path, menu, children} ; `entry` est
// le libellé que son menu parent montre, `key` le segment que TODO écrit
// pour lui dans le fil d'Ariane (`crumbs`) d'un menu. Aucune méthode ni
// aucun argument : des libellés, déjà dans la langue de la session.
import {fold} from "./model.js";

// Messages qui laissent le rejeu où il en est : ceux du hub (la session,
// l'état du terminal, un jet de frappes) et la fin d'une question.
const PASSING = ["session", "tty_state", "dropped", "answered"];

// Un libellé réduit à ses lettres et à ses chiffres, sans casse ni accents :
// icône, ponctuation et espaces ne comptent pas. "" pour un libellé qui
// n'en a aucun, qu'aucune entrée n'égale.
export function entryKey(label) {
    return fold(String(label ?? "")).replace(/[^\p{L}\p{N}]/gu, "");
}

// Plan de route du nœud au bout de `nodes`, du premier niveau jusqu'à lui :
// une étape {label, entry, key} par nœud, `entry` valant `label` pour un
// nœud qui n'en porte pas. null si `nodes` est vide, ou si une étape ne
// peut trouver son entrée : un libellé que TODO calcule à l'affichage, que
// l'arbre lit vide (« () »).
export function launchRoute(nodes) {
    const route = nodes.map(({label, entry, key}) => ({label, entry: entry ?? label, key}));
    return route.length && route.every((step) => entryKey(step.entry)) ? route : null;
}

// La clé de l'unique entrée de `items`, 0 exclue, dont le libellé égale
// `entry` au sens d'`entryKey` ; null s'il n'y en a aucune ou plusieurs.
export function matchEntry(items, entry) {
    const wanted = entryKey(entry);
    const found = wanted ? items.filter((item) => item.key !== "0" && entryKey(item.label) === wanted) : [];
    return found.length === 1 ? found[0].key : null;
}

// Le fil d'Ariane, joint par « › », du menu où se répond l'étape `at` de
// `route` : `root`, puis la clé de chaque étape d'avant.
function crumbsAt(route, root, at) {
    return [root, ...route.slice(0, at).map((step) => step.key)].join(" › ");
}

// L'étape de `route` que `question`, la question ouverte d'une session,
// peut recevoir : celle dont le menu est `question` — le menu principal
// (0), ou un menu du chemin, que TODO rend après la commande d'une feuille.
// null pour une question qui n'est pas un menu, un menu hors du chemin, ou
// un menu auquel la page a déjà répondu (`pending`).
export function resumeAt(question, pending, route, root) {
    if (question?.t !== "menu" || pending === question.qid) {
        return null;
    }
    const crumbs = (question.crumbs ?? []).join(" › ");
    for (let at = route.length - 1; at >= 0; at--) {
        if (crumbs === crumbsAt(route, root, at)) {
            return at;
        }
    }
    return null;
}

// Rejeu de `route` à partir de l'étape `at`, dont le menu a pour fil
// d'Ariane `root` suivi des clés des étapes d'avant.
export function startReplay(route, root, at = 0) {
    return {route, root, at};
}

// Un pas du rejeu `replay` à la réception de `message` : {replay, answer?,
// halt?}. `replay`, le rejeu qui continue, ou null ; `answer`, {qid, key},
// la réponse à envoyer ; `halt`, le libellé de l'étape où le chemin
// s'interrompt. Un menu dont le fil d'Ariane entier est celui de l'étape
// attendue (`crumbsAt`) reçoit son entrée ; la dernière répondue, le rejeu
// finit. Un autre menu, fût-il du même nom sous un autre parent, ou tout
// message hors PASSING (une question, un avis, une commande, la fin de la
// session), arrête le rejeu à l'étape répondue, qui ne s'est pas ouverte
// comme attendu ; une entrée introuvable ou ambiguë l'arrête à l'étape
// cherchée. Le rejeu ne répond qu'à un menu.
export function advance(replay, message) {
    if (PASSING.includes(message.t)) {
        return {replay};
    }
    const {route, root, at} = replay;
    if (message.t !== "menu" || (message.crumbs ?? []).join(" › ") !== crumbsAt(route, root, at)) {
        return {replay: null, halt: route[Math.max(at - 1, 0)].label};
    }
    const key = matchEntry(message.items ?? [], route[at].entry);
    if (key === null) {
        return {replay: null, halt: route[at].label};
    }
    const next = at + 1 < route.length ? {...replay, at: at + 1} : null;
    return {replay: next, answer: {qid: message.qid, key}};
}
