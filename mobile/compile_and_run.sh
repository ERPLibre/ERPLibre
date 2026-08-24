#!/usr/bin/env bash

if [[ ! -d "./mobile/erplibre_home_mobile" ]]; then
  echo "Please, run installation ./mobile/install_mobile_dev.sh before run this script ./mobile/compile_and_run.sh"
  exit 1
fi

WORKSPACE="$(pwd)"

cd mobile/erplibre_home_mobile || exit 1

npm install
npm run build || exit 1

# Le transfert des dépôts du manifeste DANS l'application est ce qui fait
# l'intérêt de son navigateur de code hors ligne, et il peut être vide sans que
# la compilation le dise. Ces dépôts entrent dans des conteneurs — un APK est
# un ZIP borné à 65535 entrées, quand un fichier par source en réclamait
# 124 350 —
# soit une archive tar.gz par dépôt, soit des tranches pack. Le vérificateur
# accepte les deux, prouve la présence de CHAQUE fichier promis, et relit un
# échantillon octet pour octet contre la source. Quatre pannes qu'un
# « build OK » passe sous silence : transfert vide, conteneur absent, index qui
# promet un fichier que son conteneur n'a pas, octets qui diffèrent.
#
# Même vérification que l'installation d'une VM, même script : une seule
# autorité.
"${WORKSPACE}/script/mobile/check_bundle_transfer.py" . --workspace "${WORKSPACE}" || exit 1

npx cap sync || exit 1
npx cap run android

cd - || exit 1
