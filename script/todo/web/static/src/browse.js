// Ce que montre le sélecteur de chemins, sans OWL ni DOM. Un répertoire
// est la réponse de /api/fs : {path, parent, entries[{name, dir, size}],
// truncated}, et `error` et `file` quand il ne se liste pas. Les chemins
// sont absolus, à la manière de POSIX.
import {fold} from "./model.js";

// Les erreurs fixes d'une liste, par genre, et la clé qui les traduit.
const LISTING_ERROR_LABELS = {
    busy: "Too many reads at once, try again",
    timeout: "The read took too long",
    relative: "Not an absolute path",
    refused: "Session refused, reload the page",
    unencodable: "A character that cannot be sent",
};
// Le jeton de chaque genre : ceux du hub (/api/fs), puis ceux que la page
// pose quand sa demande échoue, `HTTP 403` (la session ou son jeton
// refusés) et `URIError` (un chemin qu'`encodeURIComponent` ne code pas,
// un demi-substitut isolé).
const LISTING_ERROR_TOKENS = {
    busy: "busy",
    timeout: "timed out",
    relative: "not an absolute path",
    refused: "HTTP 403",
    unencodable: "URIError",
};

// L'adresse qui liste `path`, ses sous-répertoires seuls avec `directory`.
export function listingUrl(path, directory) {
    return `/api/fs?path=${encodeURIComponent(path)}&dirs=${directory ? 1 : 0}`;
}

// Les segments de `path` à cliquer, la racine d'abord : [{label, path}].
export function pathCrumbs(path) {
    const crumbs = [{label: "/", path: "/"}];
    let current = "";
    for (const part of path.split("/").filter(Boolean)) {
        current += `/${part}`;
        crumbs.push({label: part, path: current});
    }
    return crumbs;
}

// Le chemin de l'entrée `name` du répertoire `dir`.
export function childPath(dir, name) {
    return dir.endsWith("/") ? `${dir}${name}` : `${dir}/${name}`;
}

// Le chemin que désigne `typed` depuis le répertoire `dir` : un chemin
// absolu, ou qui part de « ~ », tel quel (le hub développe « ~ ») ; tout
// autre, relatif à `dir`. null pour un texte blanc.
export function typedPath(dir, typed) {
    if (!typed.trim()) {
        return null;
    }
    if (typed.startsWith("/") || typed === "~" || typed.startsWith("~/")) {
        return typed;
    }
    return childPath(dir, typed);
}

// Ce que devient la réponse de /api/fs à un chemin tapé : quand TODO
// demande un fichier, un fichier qui existe est la réponse (`answer`) ;
// tout le reste se montre (`show`), erreur comprise.
export function typedOutcome(listing, directory) {
    return listing.file && !directory ? {answer: listing.path} : {show: listing};
}

// Les entrées dont le nom contient `query`, sans casse ni accents ; toutes
// pour un filtre blanc.
export function filterEntries(entries, query) {
    const wanted = fold(query.trim());
    return wanted ? entries.filter((entry) => fold(entry.name).includes(wanted)) : entries;
}

// L'état du sélecteur qui montre `listing` : le champ du chemin suit le
// répertoire, le filtre et le refus s'effacent, et le widget se désarme.
// Chaque liste est un nouvel écran de boutons : le second clic d'un
// double-clic sur un répertoire tomberait sinon sur l'entrée qui prend sa
// place dans la liste qui s'ouvre, et y répondrait. Le widget se réarme
// ARM ms après que la liste paraît, comme à son apparition.
export function shownListing(listing) {
    return {listing, typed: listing.path, filter: "", refused: false, armed: false};
}

// La clé de traduction de l'erreur `error` d'une liste, quand c'est un
// jeton fixe (LISTING_ERROR_TOKENS) ; null pour une autre, la raison du
// système (`strerror`) comprise, qui s'affiche telle quelle.
export function listingErrorKey(error) {
    const kind = Object.keys(LISTING_ERROR_TOKENS).find((name) => LISTING_ERROR_TOKENS[name] === error);
    return kind ? LISTING_ERROR_LABELS[kind] : null;
}
