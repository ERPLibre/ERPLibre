#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque SOURCÉE : l'édition d'un app.ini de Forgejo qui existe déjà.
# La sourcer ne fait rien d'autre que définir ses fonctions.
#
# La seule édition permise d'un app.ini existant est clé par clé, jamais une
# réécriture : le fichier porte les secrets de la forge (SECRET_KEY,
# INTERNAL_TOKEN, JWT_SECRET) et les réglages de l'opérateur, qui sortent
# octet pour octet tels qu'ils sont entrés.

# « ini_poser SECTION CLE VALEUR » : filtre de l'entrée standard vers la
# sortie standard qui pose « CLE = VALEUR » dans [SECTION].
#
# - SECTION se compare exactement : [repository] ne désigne jamais
#   [repository.pull-request].
# - Une ligne CLE existante de la section est remplacée ; une ligne qui porte
#   déjà VALEUR reste telle quelle, ce qui rend le filtre idempotent octet
#   pour octet.
# - Une section sans la clé la reçoit juste après son en-tête.
# - Une section absente s'ajoute à la fin, précédée d'une ligne vide.
# - Toute autre ligne passe intacte : les clés d'avant la première section,
#   la même CLE dans une autre section, les commentaires et les secrets.
#
# VALEUR ne porte jamais de secret : elle passe donc en argument à awk.
ini_poser() {
    local section="$1" cle="$2" valeur="$3"
    awk -v s="$section" -v k="$cle" -v v="$valeur" '
        function nu(texte) {
            sub(/^[ \t]+/, "", texte)
            sub(/[ \t\r]+$/, "", texte)
            return texte
        }
        # La clé d une ligne « CLE = valeur », ou "" pour une autre ligne.
        function cle_de(ligne,  i) {
            i = index(ligne, "=")
            return i ? nu(substr(ligne, 1, i - 1)) : ""
        }
        function valeur_de(ligne) {
            return nu(substr(ligne, index(ligne, "=") + 1))
        }
        { l[NR] = $0 }
        END {
            cible = "[" s "]"
            courante = ""
            entete = 0
            presente = 0
            for (i = 1; i <= NR; i++) {
                t = nu(l[i])
                if (t ~ /^\[[^]]*\]$/) {
                    courante = t
                    if (courante == cible && !entete) entete = i
                    continue
                }
                if (courante == cible && cle_de(l[i]) == k) {
                    remplacer[i] = (valeur_de(l[i]) != v)
                    presente = 1
                }
            }
            for (i = 1; i <= NR; i++) {
                if (i in remplacer && remplacer[i]) {
                    print k " = " v
                    continue
                }
                print l[i]
                if (i == entete && !presente) print k " = " v
            }
            if (!entete) printf "\n%s\n%s = %s\n", cible, k, v
        }
    '
}
