# Documentation multilingue

La documentation est bilingue via **mmg** : les sources sont les `.base.md`,
qui génèrent `FICHIER.md` (anglais) et `FICHIER.fr.md` (français).

- **Ne jamais modifier directement** un `.md` ou `.fr.md` généré : la
  modification est perdue au prochain `make doc_markdown`. Éditer le
  `.base.md` correspondant.

Le mode d'emploi complet (marqueurs, en-tête obligatoire, i18n du CLI TODO)
est dans la skill `erplibre-doc-i18n`.
