#!/usr/bin/env bash

if [[ ! -d "./mobile/erplibre_home_mobile" ]]; then
  echo "Please, run installation ./mobile/install_mobile_dev.sh before run this script ./mobile/compile_and_run.sh"
  exit 1
fi

# `--lan-cleartext` produit l'APK de DEMONSTRATION, qui tolere le HTTP en
# clair vers une adresse du reseau local. Sans lui, Android refuse la requete
# AVANT que l'application la voie — « Cleartext HTTP traffic to <adresse> not
# permitted » — et la passerelle en Wi-Fi ne joint rien. Comme une
# reconstruction ordinaire remplace l'APK de demonstration en silence, la
# demonstration Wi-Fi retombe a chaque passage ici sans cette option.
LAN_CLEARTEXT=""
for argument in "$@"; do
  case "$argument" in
    --lan-cleartext) LAN_CLEARTEXT="oui" ;;
    *) echo "argument inconnu : $argument"; exit 1 ;;
  esac
done

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

if [[ -n "${LAN_CLEARTEXT}" ]]; then
  # `cap run` ne sait pas passer une propriete a gradle : on construit et on
  # pose nous-memes, puis on ouvre l'application comme il l'aurait fait.
  echo
  echo "  ⚠️  APK de DEMONSTRATION : le HTTP en clair est tolere par le"
  echo "      systeme. Numeros et corps des messages circulent alors en"
  echo "      clair sur le reseau. A ne pas laisser sur un appareil qui"
  echo "      sert autre chose qu'une demonstration."
  echo
  (cd android && ./gradlew :app:assembleDebug -PlanCleartext) || exit 1
  adb install -r android/app/build/outputs/apk/debug/app-debug.apk || exit 1
  adb shell monkey -p ca.erplibre.home \
    -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
else
  npx cap run android
fi

cd - || exit 1
