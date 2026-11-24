#!/bin/sh
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# rdp.sh ETIQUETTE IP PORT SECURITE MODE [ATTENTE]
#
# Exécuté DANS le conteneur client. Le mot de passe se lit dans /pw/good
# quand l'étiquette commence par « good », dans /pw/bad sinon : il ne paraît
# sur aucune ligne de commande de l'hôte. SECURITE vaut « - » ou une option
# FreeRDP telle que « /sec:tls ».
#
# MODE auth : « /auth-only », qui n'ouvre aucune session ; imprime « rc=N ».
# MODE conn : connexion réelle pendant ATTENTE secondes sur un Xvfb privé ;
# imprime « alive=1 » si le client vit encore au bout du délai (écran
# capturé dans /out/rdp_ETIQUETTE.xwd), « alive=0 rc=N » s'il est sorti.
# Le journal du client va dans /out/rdp_ETIQUETTE.log.
ETIQ=$1; IP=$2; PORT=$3; SEC=$4; MODE=$5; ATTENTE=${6:-35}
[ "$SEC" = - ] && SEC=
case $ETIQ in good*) P=$(cat /pw/good);; *) P=$(cat /pw/bad);; esac
if [ "$MODE" = auth ]; then
  xfreerdp3 /auth-only /v:"$IP:$PORT" /u:erplibre /p:"$P" /cert:ignore $SEC \
    > "/out/rdp_$ETIQ.log" 2>&1
  echo "rc=$?"; exit 0
fi
D=:$((10 + $(od -An -N1 -tu1 /dev/urandom) % 80))
# « --network host » partage l'espace des sockets abstraites avec l'hôte et
# les autres conteneurs : deux tirages du même numéro, et le second Xvfb
# meurt (« Cannot establish any listening sockets ») tandis que xfreerdp et
# xwd rejoignent en silence l'Xvfb de l'autre. « -nolisten local » ne laisse
# que /tmp/.X11-unix, propre au conteneur.
Xvfb $D -nolisten tcp -nolisten local -screen 0 1280x800x24 \
  >/dev/null 2>&1 & X=$!
sleep 2
kill -0 $X 2>/dev/null || { echo "alive=0 rc=xvfb"; exit 0; }
DISPLAY=$D xfreerdp3 /v:"$IP:$PORT" /u:erplibre /p:"$P" /cert:ignore $SEC \
  /size:1280x800 > "/out/rdp_$ETIQ.log" 2>&1 & pid=$!
# Une touche Maj à la douzième seconde, comme un utilisateur qui arrive :
# un écran verrouillé immobile ne produit sinon aucune image nouvelle.
i=0
while [ $i -lt "$ATTENTE" ]; do
  kill -0 $pid 2>/dev/null || break
  sleep 1; i=$((i+1))
  [ $i = 12 ] && DISPLAY=$D xdotool key shift 2>/dev/null
done
if kill -0 $pid 2>/dev/null; then
  xwd -root -display $D -out "/out/rdp_$ETIQ.xwd"; kill $pid; echo "alive=1"
else
  wait $pid; echo "alive=0 rc=$?"
fi
kill $X 2>/dev/null
exit 0
