// Ce que montrent les vues Arbre, Liste et Kanban, sans OWL ni DOM :
// recherche et tri de l'arbre des menus, vue et tri tirés du fragment de
// l'URL. Un nœud est celui de /api/telemetry : {key, label, entry, path,
// menu, children, section?} ; `counts` associe un chemin à son compteur.

export const VIEWS = ["tree", "list", "kanban", "system", "sessions", "history"];
// Tris offerts par vue ; le premier est celui de la vue quand le fragment
// n'en nomme aucun qu'elle offre.
export const SORTS = {
    tree: ["code", "usage"],
    list: ["usage", "name", "code"],
    kanban: ["usage", "name", "code"],
};

// Vues pendant lesquelles la page relit /api/telemetry : celles de l'arbre,
// et Sessions, sous laquelle la bannière dit que le code a changé.
export const CODE_VIEWS = ["tree", "list", "kanban", "sessions"];

// Vrai quand la page relit /api/telemetry : une vue de CODE_VIEWS, la page
// visible (`visibility`, celle de document.visibilityState).
export function pollsCode(view, visibility) {
    return CODE_VIEWS.includes(view) && visibility === "visible";
}

// Vrai quand l'empreinte `code` des sources de l'arbre n'est plus
// `baseline`, celle du code que tourne la session courante de la page. Une
// empreinte absente, ou pas de session, ne dit rien.
export function codeChanged(baseline, code) {
    return Boolean(baseline && code && baseline !== code);
}

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

// Feuilles sous `node`, dans l'ordre du code : {node, nodes, path}, `nodes`
// les nœuds du premier niveau jusqu'à la feuille, racine exclue, et `path`
// leurs libellés traduits joints.
export function leaves(node, trail = []) {
    return node.children.flatMap((child) => {
        const here = [...trail, child];
        const path = here.map((step) => step.label).join(" › ");
        return child.menu ? leaves(child, here) : [{node: child, nodes: here, path}];
    });
}

// Feuilles dont le chemin traduit contient `query`, rangées par `sort` :
// « usage » (compteur décroissant), « name » (libellé sans icône, selon
// `lang`) ou « code ». Tri stable.
export function listRows(tree, counts, query, sort, lang) {
    return rankRows(leaves(tree), counts, query, sort, lang);
}

// Colonnes du Kanban, comme `_command_columns` de la TUI : une par menu qui
// porte des feuilles, dans l'ordre du code (profondeur d'abord). Une
// colonne est {node, path, cards} : `node` son menu, `path` les libellés
// traduits depuis le premier niveau, `cards` ses feuilles, rangées comme
// celles de la Liste (`listRows`). Une colonne dont aucune carte ne reste
// n'est pas rendue ; par usage, les colonnes vont aussi par compteur
// décroissant de leur menu.
export function kanbanColumns(tree, counts, query, sort, lang) {
    const columns = [];
    const walk = (node, nodes) => {
        const here = node.children.filter((child) => !child.menu);
        const cards = rankRows(leaves({children: here}, nodes), counts, query, sort, lang);
        if (cards.length) {
            columns.push({node, path: nodes.map((step) => step.label).join(" › ") || node.label, cards});
        }
        for (const child of node.children) {
            if (child.menu) {
                walk(child, [...nodes, child]);
            }
        }
    };
    walk(tree, []);
    if (sort === "usage") {
        columns.sort((a, b) => usage(counts, b.node) - usage(counts, a.node));
    }
    return columns;
}

// `rows` ({node, path}) dont le chemin contient `query`, rangées par `sort`
// (voir `listRows`).
function rankRows(rows, counts, query, sort, lang) {
    const wanted = fold(query.trim());
    const kept = rows.filter((row) => fold(row.path).includes(wanted));
    if (sort === "usage") {
        kept.sort((a, b) => usage(counts, b.node) - usage(counts, a.node));
    } else if (sort === "name") {
        const collator = new Intl.Collator(lang, {sensitivity: "base"});
        kept.sort((a, b) => {
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
    return kept;
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
