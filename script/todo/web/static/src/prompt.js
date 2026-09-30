// Ce que montrent les widgets des questions de TODO, sans OWL ni DOM. Un
// menu est le message `menu` du worker : {qid, crumbs, items[{key, label,
// section, speak}], speak…} ; ses entrées se groupent par section, l'entrée
// 0 à part, et se choisissent au clavier comme au CLI. Une question est le
// message `ask` : {qid, kind, text, default, timeout_s?, options?, multi?,
// expected?}. Une réponse est ce que le hub accepte de porter au worker.
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
// que cette invite : le reste n'est qu'au terminal. Un menu sans entrée
// n'a pas de boutons qui le porteraient.
export function carriesScreen(question) {
    const items = question?.t === "menu" ? question.items ?? [] : [];
    if (!items.length) {
        return false;
    }
    const starts = String(question.text ?? "")
        .split("\n")
        .map((line) => line.trimStart());
    return items.every((item) => starts.some((line) => line.startsWith(`[${item.key}]`)));
}

// Ce que le widget d'un menu écrit au-dessus de ses entrées : pour un menu
// qui porte tout son écran, les lignes que ses entrées ne disent pas
// (`notes` : une ligne d'état, une note) ; pour un menu lu sur la sortie
// qui précède son invite, cette invite ; pour un choix, son texte sans ses
// options.
export function menuText(question) {
    return carriesScreen(question) ? (question.notes ?? []).join("\n") : promptText(question);
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

// Vrai quand le filtre, en usage (`query` non blanc), ne laisse aucune
// entrée autre que 0 : le widget le dit. Sans filtre, un menu qui n'a que
// l'entrée 0 ne dit rien.
export function filterMisses(items, query) {
    return Boolean(query.trim()) && !menuGroups(filterItems(items, query)).length;
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

// Vrai quand un clic peut répondre : ni le deuxième clic d'un double-clic
// ni un suivant (`detail` > 1), qui visaient ce que l'écran montrait sous
// le premier. Un clic du clavier, Entrée ou Espace sur un bouton, a un
// `detail` de 0.
export function clickCounts(event) {
    return !(event.detail > 1);
}

// Vrai pour une touche que tient une méthode de saisie (IME) qui compose
// un caractère : l'Entrée qui valide la composition n'envoie rien. Un
// navigateur qui ne pose pas `isComposing` sur cette Entrée lui donne le
// code 229.
export function composing(event) {
    return Boolean(event.isComposing) || event.keyCode === 229;
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

// Genres de question (`ask.kind`) que la page montre en widget ; un autre
// genre reste au terminal, qui répond à tout.
export const ASK_KINDS = ["text", "secret", "confirm", "typed", "countdown", "choose", "path"];

// La réponse d'une touche à une confirmation, sans casse : « y » pour y ou
// o, « n » pour n ; null pour toute autre.
export function confirmKey(key) {
    const lower = key.toLowerCase();
    if (lower === "y" || lower === "o") {
        return "y";
    }
    return lower === "n" ? "n" : null;
}

// Vrai quand une confirmation tapée peut partir : le texte attendu exact,
// quand le message le porte (`expected`), sinon toute réponse que le hub
// accepte, vide comprise.
export function typedReady(question, value) {
    return typeof question.expected === "string" ? value === question.expected : sendable(value);
}

// Secondes entières qui restent avant `deadline` (en ms), 0 au plus bas.
export function secondsLeft(deadline, now) {
    return Math.max(0, Math.ceil((deadline - now) / 1000));
}

// La réponse d'un choix multiple : les clés cochées dans l'ordre des
// options, séparées d'une espace (« 1 3 »), comme on les taperait.
export function choiceValue(options, picked) {
    return options
        .filter((option) => picked.includes(option.key))
        .map((option) => option.key)
        .join(" ");
}

// Ce qu'envoie le bouton Tout d'un choix multiple : un mot que le port lit
// comme toutes les options, dans les deux langues.
export const ALL_ANSWER = "*";

// Les options qu'un choix multiple offre à cocher : toutes, sauf l'entrée
// 0, le retour, qui a son bouton.
export function choiceBoxes(options) {
    return options.filter((option) => option.key !== "0");
}

// Le texte d'une question sans ce que son widget montre déjà : pour un
// choix, sa question seule (`prompt`), sans ses entrées ni son invite.
export function promptText(question) {
    const text = question.kind === "choose" ? question.prompt : question.text;
    return String(text ?? "").trimEnd();
}
