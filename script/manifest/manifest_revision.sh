# Fragment à sourcer depuis la racine d'ERPLibre :
#
#     . ./script/manifest/manifest_revision.sh
#     MANIFEST_REV=$(manifest_revision) || exit 1
#
# manifest_revision rend la révision à passer à « repo init -b » : un NOM DE
# BRANCHE, jamais un SHA nu.
#
# « repo init -b <sha> » échoue sur un espace de travail NEUF : repo doit y
# cloner .repo/manifests et ne sait pas résoudre un commit en révision de
# manifeste. Il abandonne sur « unparseable HEAD », puis repo sync sur
# « manifest not found » ; -b <branche> réussit au même endroit.
# Le piège est qu'un .repo DÉJÀ initialisé accepte le SHA — le défaut reste
# donc invisible sur toute machine ayant réussi un init une fois, et ne frappe
# que les installations neuves.
#
# La branche extraite d'abord ; sur un HEAD détaché, une branche locale qui
# contient ce commit. Sans l'une ni l'autre, la fonction écrit l'erreur sur
# stderr et rend 1 : retomber sur le SHA ne marcherait pas.
manifest_revision() {
  local rev
  rev=$(git symbolic-ref --quiet --short HEAD || true)
  if [ -z "${rev}" ]; then
    rev=$(git branch --contains HEAD --format='%(refname:short)' 2>/dev/null | grep -v '[()]' | head -1)
  fi
  if [ -z "${rev}" ]; then
    echo "Erreur : impossible de déterminer une branche pour repo init." >&2
    echo "  HEAD est détaché et aucune branche ne contient ce commit." >&2
    return 1
  fi
  printf '%s\n' "${rev}"
}
