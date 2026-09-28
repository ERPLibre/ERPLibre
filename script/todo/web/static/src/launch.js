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
// Messages qui disent où une session arrive après une réponse : une
// question, ou une commande qui commence.
const LANDINGS = ["menu", "ask", "run_start"];

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
// La longueur de `route` quand `question` est le menu du nœud lancé
// lui-même : la session y est déjà. null pour une question qui n'est pas un
// menu, un menu hors du chemin, ou un menu auquel la page a déjà répondu
// (`pending`).
export function resumeAt(question, pending, route, root) {
    if (question?.t !== "menu" || pending === question.qid) {
        return null;
    }
    const crumbs = (question.crumbs ?? []).join(" › ");
    for (let at = route.length; at >= 0; at--) {
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

// Vrai quand la session `view` attend à un menu, sans réponse de la page ni
// commande en cours : la fermer n'interrompt rien.
export function idleAtMenu({status, question, pending, running}) {
    return status === "open" && question?.t === "menu" && pending !== question.qid && !running;
}

// Ce que la vue Sessions fait d'un ordre de la page : `order` est {route,
// root}, le plan de route d'un nœud et le fil d'Ariane du menu principal,
// ou {reopen: true}, une session neuve sans rejeu. `view` est l'état de la
// session courante : {status, id, question, pending, running, moving,
// replaying, renewing, waiting}, `moving` vrai d'une réponse prise jusqu'à
// ce qui la suit (`movingAfter`), `replaying` vrai pendant un rejeu,
// `renewing` l'ordre qui attend la fin de la session que `renew` ferme,
// `waiting` l'acte ("attach" ou "wait") d'un ordre qui attend déjà. Rend
// {act} :
// - "queue" : une session se ferme pour une neuve ; l'ordre prend la place
//   de celui que la neuve suivra, et jamais la session qui se ferme ;
// - "attach" : un rattachement en cours ; l'ordre attend la question
//   ouverte, qui suit `session` (`lands`) ;
// - "wait" : un rejeu en cours ou une réponse en chemin ; la session va
//   ailleurs, et l'ordre attend le message qui dit où (`lands`) ; quand un
//   ordre attend déjà (`waiting`), le nouveau prend sa place, dans le même
//   acte ;
// - "start" : une session neuve s'ouvre ; le rejeu part de son menu
//   principal ;
// - "resume", `at` : la session attend au menu de l'étape `at`, où le rejeu
//   reprend ;
// - "here" : la session attend au menu du nœud lancé ; rien à rejouer ;
// - "renew", `close` : une session neuve, la courante fermée d'abord si
//   elle attend à un menu (`idleAtMenu`) ; une session à une question ou en
//   pleine commande reste, rattachable.
export function planOrder(order, view) {
    const {status, id, question, pending, moving, replaying, renewing, waiting} = view;
    if (renewing) {
        return {act: "queue"};
    }
    if (waiting) {
        return {act: waiting};
    }
    if (status === "connecting" && !order.reopen) {
        return {act: id ? "attach" : "start"};
    }
    const open = status === "open";
    if (open && (replaying || moving || (question && pending === question.qid))) {
        return {act: "wait"};
    }
    const at = open && !order.reopen ? resumeAt(question, pending, order.route, order.root) : null;
    if (at === null) {
        return {act: "renew", close: idleAtMenu(view)};
    }
    return at === order.route.length ? {act: "here"} : {act: "resume", at};
}

// Vrai quand `message` dit où se rejoue un ordre en attente : après un
// rattachement (`attaching`), tout message qui suit `session`, la question
// ouverte venant d'abord ; après "wait", une question ou une commande qui
// commence (LANDINGS). La fin de la session le dit aussi, hors de ce
// message.
export function lands(message, attaching) {
    return attaching ? message.t !== "session" : LANDINGS.includes(message.t);
}

// `moving` après `message` : vrai dès `answered`, une réponse prise, tant
// que la session n'est pas arrivée quelque part (LANDINGS) ; faux pour une
// autre session (`session`).
export function movingAfter(moving, message) {
    if (message.t === "answered") {
        return true;
    }
    return LANDINGS.includes(message.t) || message.t === "session" ? false : moving;
}

// Vrai quand `message` est `answered` d'une question à laquelle la page n'a
// pas répondu (`pending`, le qid de sa réponse) : l'utilisateur a répondu
// au terminal.
export function answeredByHand(message, pending) {
    return message.t === "answered" && message.qid !== pending;
}
