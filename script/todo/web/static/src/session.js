// Protocole de /ws vu de la page, sans OWL ni DOM : le premier message,
// les trames des frappes, l'état que dit une fermeture, et l'identifiant de
// session que le fragment de l'URL garde pour un rechargement.

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
