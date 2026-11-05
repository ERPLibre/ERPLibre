// L'offre de source de l'AGPL §13 que rend /api/source, mise en lignes pour
// le pied de page, sans OWL ni DOM. Chaque ligne est [libellé, valeur], le
// libellé traduit par `t`, la table de traduction de la page ; une valeur
// que git n'a pas dite est « aucun » ou « aucune », accordé en français au
// libellé (`noneMasculine` pour Dépôt et Commit, `none` pour Branche), un
// état des fichiers qu'il n'a pas dit, « inconnu ». Chaque bibliothèque
// vendorée suit, avec le chemin, servi par le hub, du texte de sa licence.
const SOURCE_LABELS = {
    license: "License",
    remote: "Repository",
    commit: "Commit",
    branch: "Branch",
    modified: "Local changes",
    none: "none",
    noneMasculine: "none (masculine)",
    unknown: "unknown",
    yes: "yes",
    no: "no",
};

export function sourceRows(source, t) {
    const label = (key) => t(SOURCE_LABELS[key]);
    const or = (value, none) => value || label(none);
    let modified = label("unknown");
    if (typeof source.modified === "boolean") {
        modified = label(source.modified ? "yes" : "no");
    }
    return [
        [label("license"), source.license],
        [label("remote"), or(source.remote, "noneMasculine")],
        [label("commit"), or(source.commit, "noneMasculine")],
        [label("branch"), or(source.branch, "none")],
        [label("modified"), modified],
    ];
}

// Une bibliothèque vendorée : « nom version — licence », et le chemin du
// texte de sa licence.
export function noticeLine(notice) {
    return {text: `${notice.name} ${notice.version} — ${notice.license}`, href: notice.text};
}
