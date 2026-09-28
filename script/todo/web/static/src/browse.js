// Ce que montre le sélecteur de chemins, sans OWL ni DOM. Un répertoire
// est la réponse de /api/fs : {path, parent, entries[{name, dir, size}],
// truncated}, et `error` et `file` quand il ne se liste pas. Les chemins
// sont absolus, à la manière de POSIX.
import {fold} from "./model.js";

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
