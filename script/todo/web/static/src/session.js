// Protocole de /ws vu de la page, sans OWL ni DOM : le premier message,
// les trames des frappes, l'état que dit une fermeture, l'identifiant de
// session que le fragment de l'URL garde pour un rechargement, et quand le
// terminal se replie.
import {carriesScreen} from "./prompt.js";

// Fermetures du hub autres que la fin d'une session, qu'annonce `bye`.
const CLOSED = {1013: "full", 4001: "taken", 4404: "gone"};
// Octets par trame de frappes : le hub ferme en 1009 un message de plus de
// 64 Kio, qu'un collage peut dépasser.
export const FRAME = 32 * 1024;

// Premier message d'une connexion. Sans `session`, le hub en ouvre une ;
// avec, il s'y rattache et rejoue sa sortie à partir du décalage `after`.
export function helloMessage({csrf, lang, cols, rows, session, after}) {
    const hello = {t: "hello", csrf, lang, cols, rows};
    if (session) {
        Object.assign(hello, {session, after});
    }
    return JSON.stringify(hello);
}

// `bytes` en tranches de FRAME octets au plus, dans l'ordre. Couper un
// caractère UTF-8 est sans effet : le terminal reçoit les octets à la suite.
export function frames(bytes) {
    const out = [];
    for (let at = 0; at < bytes.length; at += FRAME) {
        out.push(bytes.subarray(at, at + FRAME));
    }
    return out;
}

// État d'une connexion fermée : « ended » après `bye`, sinon celui que dit
// le code, « lost » pour tout autre.
export function closedState(code, bye) {
    return bye ? "ended" : CLOSED[code] || "lost";
}

// Identifiant de session du fragment, ou null.
export function sessionOf(hash) {
    return new URLSearchParams(hash.replace(/^#/, "")).get("session");
}

// Fragment qui porte `id` (ou plus aucune session) et garde le reste.
export function withSession(hash, id) {
    const params = new URLSearchParams(hash.replace(/^#/, ""));
    if (id) {
        params.set("session", id);
    } else {
        params.delete("session");
    }
    return `#${params}`;
}

// Invites à réponse rapide, en fin de ligne : [y/N], (Y/n), [o/N], (O/n),
// (yes/no) et (yes/no/[fingerprint]), suivies au plus d'un « ? » ou d'un
// « : ». Rend les réponses que proposent les boutons, ou aucune.
const QUICK = /(?:\[([yo])\/n\]|\(([yo])\/n\)|\((yes)\/no(?:\/\[fingerprint\])?\))\s*[?:]?$/i;

export function quickAnswers(line) {
    const match = QUICK.exec(line);
    if (!match) {
        return [];
    }
    const yes = (match[1] || match[2] || match[3]).toLowerCase();
    return [yes, yes === "yes" ? "no" : "n"];
}

// Lignes d'une suite de rangées `{text, wrapped}` : une rangée que le
// terminal a coupée (`wrapped`, suite de la précédente) s'y rejoint.
export function joinWrapped(rows) {
    const lines = [];
    for (const {text, wrapped} of rows) {
        if (wrapped && lines.length) {
            lines[lines.length - 1] += text;
        } else {
            lines.push(text);
        }
    }
    return lines;
}

// Dernière ligne non vide, sans ses espaces de fin, ou "".
export function lastLine(lines) {
    for (let at = lines.length - 1; at >= 0; at--) {
        const line = lines[at].trimEnd();
        if (line) {
            return line;
        }
    }
    return "";
}

// Vrai quand le terminal attend un secret : écho coupé en mode canonique.
// Un texte « password: » avec l'écho actif n'en est jamais un.
export function asksSecret(tty) {
    return tty.echo === false && tty.canon === true;
}

// Phase de la vue d'une session : la question structurée ouverte (son qid),
// une commande en cours, l'écran alternatif. Le choix du bouton Terminal ne
// vaut que pour la phase où il a été fait.
export function foldPhase({question, running, altscreen}) {
    return `${question?.qid ?? 0}|${Boolean(running)}|${Boolean(altscreen)}`;
}

// Le choix du bouton Terminal ({phase, open}) quand la vue est à la phase
// `phase` : gardé dans la sienne, oublié dès qu'elle change, pour qu'une
// phase semblable plus tard — une autre commande, un autre moment sans
// question — ne le retrouve pas.
export function heldOverride(override, phase) {
    return override?.phase === phase ? override : null;
}

// Vrai quand le terminal se montre. L'invite d'un programme que TODO
// lance (un lecteur, ou l'écho coupé, sans question structurée) le montre
// toujours. Sinon le choix du bouton Terminal (`override`) l'emporte dans
// sa phase ; sinon il se montre pendant une commande (`run_start` …
// `run_end`), en écran alternatif, sous la première question après une
// commande (`ran`), dont la sortie resterait à lire, et sous toute
// question qui ne porte pas tout son écran (`carriesScreen`).
export function terminalShown({question, running, altscreen, ran, tty, override}) {
    if (!question && tty && (tty.reader === true || asksSecret(tty))) {
        return true;
    }
    if (override && override.phase === foldPhase({question, running, altscreen})) {
        return override.open;
    }
    return Boolean(running || altscreen || ran || !carriesScreen(question));
}
