// Ce que montrent les vues Arbre et Liste, sans OWL ni DOM : recherche et tri
// de l'arbre des menus, vue et tri tirés du fragment de l'URL. Un nœud est
// celui de /api/telemetry : {key, label, path, menu, children, section?} ;
// `counts` associe un chemin à son compteur.

export const VIEWS = ["tree", "list", "system", "sessions"];
// Tris offerts par vue ; le premier est celui de la vue quand le fragment
// n'en nomme aucun qu'elle offre.
export const SORTS = {tree: ["code", "usage"], list: ["usage", "name", "code"]};

// Minuscules sans accents : « Système » et « systeme » se rejoignent.
export function fold(text) {
    return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

// Libellé sans l'icône qui l'ouvre, pour le tri par nom.
function bare(label) {
    return label.replace(/^[^\p{L}\p{N}]+/u, "");
}

function usage(counts, node) {
    return counts[node.path] || 0;
}

// Sous-arbre des nœuds dont le libellé contient `query`, avec leurs
// ancêtres ; un menu qui correspond garde tous ses descendants. La racine
// n'est jamais comparée : « t », « o » ou « d » la trouveraient et
// rendraient tout l'arbre. null si rien ne correspond, l'arbre entier si
// `query` est vide.
export function filterTree(node, query) {
    const wanted = fold(query.trim());
    if (!wanted) {
        return node;
    }
    const walk = (current) => {
        if (fold(current.label).includes(wanted)) {
            return current;
        }
        const children = current.children.map(walk).filter(Boolean);
        return children.length ? {...current, children} : null;
    };
    const children = node.children.map(walk).filter(Boolean);
    return children.length ? {...node, children} : null;
}

// Copie de l'arbre dont chaque menu range ses enfants par compteur
// décroissant ; « code » rend l'arbre tel quel. Le tri est stable : à
// compteur égal, l'ordre du code.
export function sortTree(node, counts, sort) {
    if (sort !== "usage" || !node.menu) {
        return node;
    }
    const children = node.children
        .map((child) => sortTree(child, counts, sort))
        .sort((a, b) => usage(counts, b) - usage(counts, a));
    return {...node, children};
}

// Feuilles sous `node`, dans l'ordre du code : {node, path}, `path` joignant
// les libellés traduits depuis le premier niveau, racine exclue.
export function leaves(node, trail = []) {
    return node.children.flatMap((child) => {
        const here = [...trail, child.label];
        return child.menu ? leaves(child, here) : [{node: child, path: here.join(" › ")}];
    });
}

// Feuilles dont le chemin traduit contient `query`, rangées par `sort` :
// « usage » (compteur décroissant), « name » (libellé sans icône, selon
// `lang`) ou « code ». Tri stable.
export function listRows(tree, counts, query, sort, lang) {
    const wanted = fold(query.trim());
    const rows = leaves(tree).filter((row) => fold(row.path).includes(wanted));
    if (sort === "usage") {
        rows.sort((a, b) => usage(counts, b.node) - usage(counts, a.node));
    } else if (sort === "name") {
        const collator = new Intl.Collator(lang, {sensitivity: "base"});
        rows.sort((a, b) => {
            const nameA = bare(a.node.label);
            const nameB = bare(b.node.label);
            // Un libellé sans lettre ni chiffre (« () », un tiret seul, un
            // point médian) rend `bare` vide : il va après les libellés
            // nommés plutôt qu'en tête, où une chaîne vide se collerait.
            if (!nameA || !nameB) {
                return (nameA === "") - (nameB === "");
            }
            return collator.compare(nameA, nameB);
        });
    }
    return rows;
}

// Tri effectif d'une vue : `sort` s'il est offert, sinon le premier offert.
export function effectiveSort(view, sort) {
    const offered = SORTS[view] || [];
    return offered.includes(sort) ? sort : offered[0];
}

// {view, sort} du fragment. Une vue inconnue — « telemetry », le nom de la
// page que le lanceur met dans le lien — vaut l'arbre.
export function readFragment(hash) {
    const params = new URLSearchParams(hash.replace(/^#/, ""));
    const view = params.get("view");
    return {view: VIEWS.includes(view) ? view : "tree", sort: params.get("sort") || ""};
}

// Fragment qui porte `view` et `sort` et garde les autres paramètres,
// « lang » compris ; un `sort` vide en est retiré.
export function writeFragment(hash, {view, sort}) {
    const params = new URLSearchParams(hash.replace(/^#/, ""));
    params.set("view", view);
    if (sort) {
        params.set("sort", sort);
    } else {
        params.delete("sort");
    }
    return `#${params}`;
}
