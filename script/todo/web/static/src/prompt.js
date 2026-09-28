// Ce que montrent les widgets des questions de TODO, sans OWL ni DOM. Un
// menu est le message `menu` du worker : {qid, crumbs, items[{key, label,
// section, speak}], speak…} ; ses entrées se groupent par section, l'entrée
// 0 à part, et se choisissent au clavier comme au CLI. Une réponse est ce
// que le hub accepte de porter au worker.
import {fold} from "./model.js";

// Au-delà de FILTER_FROM entrées, 0 non comprise, le menu offre un filtre.
export const FILTER_FROM = 12;
// Millisecondes après la dernière touche : ce qui est tapé choisit.
export const PAUSE = 700;
// Caractères d'une réponse (`protocol.ANSWER_LIMIT` du hub).
export const ANSWER_LIMIT = 4096;
// Millisecondes après l'apparition d'un widget pendant lesquelles il
// n'accepte rien : une frappe destinée à la question d'avant, partie avant
// qu'on ait vu celle-ci, n'y répond pas.
export const ARM = 250;

// Entrées autres que 0, en groupes {section, items} dans l'ordre du menu :
// un groupe par suite d'entrées d'une même section (null hors section).
export function menuGroups(items) {
    const groups = [];
    for (const item of items) {
        if (item.key === "0") {
            continue;
        }
        const section = item.section ?? null;
        const last = groups.at(-1);
        if (last && last.section === section) {
            last.items.push(item);
        } else {
            groups.push({section, items: [item]});
        }
    }
    return groups;
}

// L'entrée 0 (Retour, Quitter), montrée à part, ou null.
export function backItem(items) {
    return items.find((item) => item.key === "0") ?? null;
}

// Vrai quand le menu offre un filtre : plus de FILTER_FROM entrées, sans
// compter l'entrée 0.
export function showsFilter(items) {
    return items.filter((item) => item.key !== "0").length > FILTER_FROM;
}

// Vrai pour un menu dont le texte liste chacune de ses entrées (« [N] » en
// début de ligne) : un menu de `fill_help_info`, ou écrit à la main et
// passé tout entier à l'invite. Ses boutons tiennent tout son écran. Un
// menu lu sur la sortie qui précède son invite (« Choice [1]: ») ne porte
// que cette invite : le reste n'est qu'au terminal.
export function carriesScreen(question) {
    if (question?.t !== "menu") {
        return false;
    }
    const starts = String(question.text ?? "")
        .split("\n")
        .map((line) => line.trimStart());
    return question.items.every((item) => starts.some((line) => line.startsWith(`[${item.key}]`)));
}

// Entrées dont le libellé contient `query`, sans casse ni accents, ou dont
// la clé est `query` ; toutes quand `query` est vide.
export function filterItems(items, query) {
    const typed = query.trim();
    const wanted = fold(typed);
    if (!wanted) {
        return items;
    }
    return items.filter((item) => item.key === typed || fold(item.label).includes(wanted));
}

// Une touche tapée dans un menu, comme au CLI. `keys` : les clés du menu ;
// `typed` : ce qui attend déjà. Rend {typed, choose} : `choose`, la clé à
// envoyer tout de suite, ou null ; `typed`, ce qui attend encore Entrée ou
// PAUSE. Une clé qu'aucune autre ne prolonge part dès sa dernière touche
// (« 5 » quand il n'y a pas de « 50 ») ; une touche qui ne mène à aucune clé
// efface ce qui attendait. Entrée choisit ce qui attend, s'il est une clé.
export function menuKey(keys, typed, key) {
    if (key === "Enter") {
        return {typed: "", choose: keys.includes(typed) ? typed : null};
    }
    if (key === "Backspace") {
        return {typed: typed.slice(0, -1), choose: null};
    }
    if (key === "Escape") {
        return {typed: "", choose: null};
    }
    if (!/^[0-9A-Za-z]$/.test(key)) {
        return {typed, choose: null};
    }
    const next = typed + key;
    const longer = keys.some((other) => other.length > next.length && other.startsWith(next));
    if (keys.includes(next) && !longer) {
        return {typed: "", choose: next};
    }
    return {typed: longer || keys.includes(next) ? next : "", choose: null};
}

// Ce qui attend quand vient la PAUSE : la clé à envoyer, ou null.
export function menuPause(keys, typed) {
    return keys.includes(typed) ? typed : null;
}

// Vrai quand une touche (`keydown`) peut répondre au widget paru à
// `shownAt` : ni la répétition d'une touche tenue, ni une touche partie
// moins de ARM ms après lui (`event.timeStamp`, de la même horloge que
// `performance.now()`).
export function keyCounts(event, shownAt) {
    return !event.repeat && event.timeStamp - shownAt >= ARM;
}

// Vrai quand la page peut répondre à la question `qid` : c'est la question
// ouverte (`question`), et la page ne lui a pas déjà répondu (`pending`).
// Le widget d'une question close, encore à l'écran, ne répond pas à la
// suivante.
export function answerable(question, pending, qid) {
    return question?.qid === qid && pending !== qid;
}

// Vrai pour une réponse que le hub porte au worker : une ligne d'au plus
// ANSWER_LIMIT caractères, sans caractère de contrôle (C0, DEL, C1) ni
// demi-substitut isolé. Le hub refuse le reste sans rien dire.
export function sendable(value) {
    return (
        typeof value === "string" &&
        value.isWellFormed() &&
        [...value].length <= ANSWER_LIMIT &&
        !/[\u0000-\u001f\u007f-\u009f]/.test(value)
    );
}
