# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Groupes de processus : une commande, sa propre session, et l'arrêt de
TOUT ce qu'elle a lancé.

Une commande lancée par `lancer` ouvre sa propre session : elle est chef
d'un groupe de processus dont tous ses descendants font partie, n'a pas de
terminal de contrôle et lit /dev/null sauf demande contraire. Aucune invite
(mot de passe, clé d'hôte) ne peut donc s'ouvrir, et le Ctrl+C du terminal
ne l'atteint pas : c'est son propriétaire qui l'arrête, par `Groupe.tuer`
ou, pour plusieurs commandes, par `Lot.arreter`.

Invariant : le groupe n'est signalé (os.killpg) que tant que son chef n'est
pas récolté. Un chef sorti mais non récolté (zombie) garde son numéro, qui
ne peut être réattribué ; une fois récolté, ce numéro peut désigner le
groupe d'un tout autre programme. La récolte et le signal passent donc par
le même verrou, et le processus ne se récolte que par ce module :
`Groupe.processus` sert à lire `stdout` ou écrire `stdin`, jamais à
appeler wait(), poll() ou communicate().

Sous Linux, l'attente passe par un pidfd, qui signale la sortie du chef
sans le récolter : le groupe est alors balayé (SIGKILL aux descendants
restés) pendant que le numéro est encore réservé. Sans pidfd, l'attente
voit la sortie par os.waitid(WNOWAIT), sondé : même garantie, moins
réactif.

Usage avec un pool de fils : `with ThreadPoolExecutor(...) as pool,
Lot() as lot:` — le Lot se ferme AVANT que le pool attende ses fils, sans
quoi la sortie du `with` attend la fin naturelle de chaque commande.

La grâce (`grace`, en secondes) est une propriété de ce qu'on lance :
SIGTERM d'abord, de quoi écrire des données de couverture ou supprimer une
base de test, puis SIGKILL à ce qui reste. Elle n'aide que l'enfant qui
sait traiter SIGTERM ; 0 tue aussitôt.

Ce que le module ne couvre pas : un descendant qui ouvre lui-même une
nouvelle session (setsid, démon) quitte le groupe et survit à l'arrêt.
Linux et les systèmes POSIX seulement : ni session ni killpg ailleurs.
"""

import contextlib
import os
import select
import signal
import subprocess
import threading
import time

_pidfd_open = getattr(os, "pidfd_open", None)

# Au-delà, `Lot.arreter` rend la main sur un groupe tué mais pas récolté.
RECOLTE_MAX = 5.0

# Arguments de Popen que ce module fixe lui-même : les accepter de
# l'appelant romprait l'invariant de session.
_RESERVES = ("start_new_session", "process_group", "preexec_fn")


def lancer(cmd, *, grace=0.0, **popen):
    """Un Groupe dont `cmd` est le chef, dans une nouvelle session.

    `grace` : secondes laissées après SIGTERM avant SIGKILL quand le groupe
    est tué sans grâce explicite. `popen` va à subprocess.Popen ; stdin vaut
    /dev/null par défaut, une session sans terminal ne lisant pas le
    clavier."""
    for nom in _RESERVES:
        if nom in popen:
            raise TypeError(f"lancer() fixe lui-même {nom}")
    popen.setdefault("stdin", subprocess.DEVNULL)
    return Groupe(
        subprocess.Popen(cmd, start_new_session=True, **popen), grace
    )


class Groupe:
    """Un processus chef de session et le groupe qu'il mène."""

    def __init__(self, processus, grace=0.0):
        self.processus = processus
        self.pid = processus.pid
        self.grace = grace
        self._verrou = threading.Lock()
        self._recolte = False
        self._lecteurs = None
        self._lus = {}
        self._quand_recolte = []
        # Échéance de la grâce en cours (time.monotonic), ou None : tant
        # qu'elle court, la sortie du chef n'abrège pas celle de ses
        # descendants.
        self._fin_grace = None

    @property
    def code(self):
        """Le code de sortie du chef, None tant qu'il n'est pas récolté."""
        return self.processus.returncode if self._recolte else None

    def signaler(self, sig):
        """Envoie `sig` à tout le groupe. Faux si le chef est déjà récolté
        ou si plus personne n'est dans le groupe."""
        with self._verrou:
            if self._recolte:
                return False
            try:
                os.killpg(self.pid, sig)
            except (ProcessLookupError, PermissionError):
                return False
            return True

    def attendre(self, timeout=None):
        """Le code de sortie du chef, une fois récolté et le groupe balayé.

        Lève subprocess.TimeoutExpired après `timeout` secondes sans rien
        tuer : l'appelant décide. Plusieurs fils peuvent attendre le même
        groupe."""
        echeance = None if timeout is None else time.monotonic() + timeout
        if _pidfd_open is not None:
            self._attendre_pidfd(echeance, timeout)
        else:
            self._attendre_poll(echeance, timeout)
        return self.processus.returncode

    def _attendre_pidfd(self, echeance, timeout):
        with self._verrou:
            if self._recolte:
                return
            try:
                fd = _pidfd_open(self.pid)
            except OSError:
                fd = None
        if fd is None:
            self._attendre_poll(echeance, timeout)
            return
        try:
            sonde = select.poll()
            sonde.register(fd, select.POLLIN)
            while not sonde.poll(_reste_ms(echeance)):
                if echeance is not None and time.monotonic() >= echeance:
                    raise subprocess.TimeoutExpired(
                        self.processus.args, timeout
                    )
        finally:
            os.close(fd)
        self._recolter(balayer_avant=True)

    def _attendre_poll(self, echeance, timeout):
        """Sans pidfd : waitid(WNOWAIT) voit la sortie sans récolter, ce qui
        garde le balayage avant la récolte. Sondé, pause croissante."""
        pause = 0.001
        while True:
            with self._verrou:
                if self._recolte:
                    return
                sorti = os.waitid(
                    os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                )
            if sorti is not None:
                break
            if echeance is not None and time.monotonic() >= echeance:
                raise subprocess.TimeoutExpired(self.processus.args, timeout)
            time.sleep(pause)
            pause = min(pause * 2, 0.05)
        self._recolter(balayer_avant=True)

    def _recolter(self, balayer_avant):
        if balayer_avant:
            # Pendant une grâce, le chef peut sortir avant ses descendants,
            # qui sauvent encore leurs données : on leur laisse la fin de
            # la grâce. Le chef, zombie non récolté, réserve le numéro du
            # groupe pendant ce temps.
            fin = self._fin_grace
            pause = 0.02
            while (
                fin is not None
                and time.monotonic() < fin
                and _autres_membres(self.pid)
            ):
                # Relire /proc coûte quelques millisecondes : la pause
                # s'allonge, chaque fil qui attend un groupe en fait autant.
                time.sleep(pause)
                pause = min(pause * 2, 0.25)
                fin = self._fin_grace
        with self._verrou:
            if self._recolte:
                return
            if balayer_avant:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(self.pid, signal.SIGKILL)
            self.processus.wait()
            self._recolte = True
        self._apres_recolte()

    def _apres_recolte(self):
        for rappel in self._quand_recolte:
            rappel(self)

    def tuer(self, grace=None, premier=signal.SIGTERM):
        """Arrête le groupe et rend le code du chef.

        Avec une grâce, `premier` d'abord (SIGTERM : de quoi sauver des
        données ou supprimer une base), puis SIGKILL à ce qui reste après
        `grace` secondes. Un Ctrl+C pendant la grâce tue aussitôt."""
        grace = self.grace if grace is None else grace
        if grace <= 0:
            self._fin_grace = None
            self.signaler(signal.SIGKILL)
            return self.attendre()
        self._fin_grace = time.monotonic() + grace
        self.signaler(premier)
        try:
            return self.attendre(grace)
        except subprocess.TimeoutExpired:
            pass
        except BaseException:
            self._fin_grace = None
            self.signaler(signal.SIGKILL)
            raise
        self._fin_grace = None
        self.signaler(signal.SIGKILL)
        return self.attendre()

    def communiquer(self, entree=None, timeout=None):
        """(stdout, stderr) comme Popen.communicate, chaque flux non PIPE
        valant None.

        Les flux sont lus par des fils : la fin du chef suffit, même si un
        descendant tenait le tube, puisque le balayage le ferme. Après un
        TimeoutExpired, un nouvel appel reprend la lecture en cours."""
        p = self.processus
        echeance = None if timeout is None else time.monotonic() + timeout
        if self._lecteurs is None:
            self._lecteurs = []
            for nom in ("stdout", "stderr"):
                flux = getattr(p, nom)
                if flux is not None:
                    fil = threading.Thread(
                        target=self._lire, args=(nom, flux), daemon=True
                    )
                    fil.start()
                    self._lecteurs.append(fil)
            if p.stdin is not None:
                with contextlib.suppress(BrokenPipeError, OSError):
                    if entree:
                        p.stdin.write(entree)
                    p.stdin.close()
        self.attendre(
            None if echeance is None else max(0, echeance - time.monotonic())
        )
        for fil in self._lecteurs:
            fil.join(
                None
                if echeance is None
                else max(0, echeance - time.monotonic())
            )
            if fil.is_alive():
                raise subprocess.TimeoutExpired(p.args, timeout)
        return self._lus.get("stdout"), self._lus.get("stderr")

    def _lire(self, nom, flux):
        try:
            self._lus[nom] = flux.read()
        finally:
            flux.close()


def membres(pgid):
    """Les PID vivants du groupe `pgid`, son chef compris, lus dans
    /proc ; None sans /proc (le système ne permet pas de les connaître).

    Suit le GROUPE et non la filiation : un descendant dont le parent est
    mort, rattaché à init, reste membre de son groupe."""
    try:
        noms = os.listdir("/proc")
    except OSError:
        return None
    trouves = []
    for nom in noms:
        if not nom.isdigit():
            continue
        try:
            with open(f"/proc/{nom}/stat", encoding="utf-8") as fh:
                champs = fh.read().rsplit(")", 1)[1].split()
        except (OSError, IndexError, UnicodeDecodeError):
            continue
        # champs[0] : l'état ; champs[2] : le groupe de processus.
        if len(champs) > 2 and champs[2] == str(pgid) and champs[0] != "Z":
            trouves.append(int(nom))
    return trouves


def _autres_membres(pgid):
    """Vrai si un processus vivant autre que le chef `pgid` est encore dans
    son groupe. Sans /proc, on suppose que oui, et la grâce court jusqu'à
    son terme."""
    trouves = membres(pgid)
    return True if trouves is None else any(p != pgid for p in trouves)


def _reste_ms(echeance):
    if echeance is None:
        return None
    return max(0, int((echeance - time.monotonic()) * 1000) + 1)


class Lot:
    """Des groupes lancés ensemble, arrêtés ensemble.

    `arreter` refuse tout lancement ultérieur et signale chaque groupe en
    cours ; un `lancer` concurrent est soit refusé (None), soit compté et
    donc signalé : le verrou couvre la création du processus. Après le
    retour d'`arreter`, aucun groupe du lot ne peut plus naître."""

    def __init__(self, grace=0.0):
        self.grace = grace
        self._verrou = threading.Lock()
        self._actifs = set()
        self._arrete = False

    @property
    def arrete(self):
        return self._arrete

    def actifs(self):
        with self._verrou:
            return list(self._actifs)

    def lancer(self, cmd, **popen):
        """Le Groupe de `cmd`, ou None une fois le lot arrêté."""
        popen.setdefault("grace", self.grace)
        with self._verrou:
            if self._arrete:
                return None
            groupe = lancer(cmd, **popen)
            groupe._quand_recolte.append(self._retirer)
            self._actifs.add(groupe)
        return groupe

    def _retirer(self, groupe):
        with self._verrou:
            self._actifs.discard(groupe)

    def arreter(self, grace=None, premier=signal.SIGTERM):
        """Refuse les lancements et arrête les groupes en cours.

        Sans grâce, SIGKILL et retour immédiat : les fils qui attendent
        récoltent. Avec grâce, `premier` puis, au plus `grace` secondes
        après, SIGKILL aux survivants. Idempotent ; un Ctrl+C pendant la
        grâce tue aussitôt et se propage."""
        grace = self.grace if grace is None else grace
        with self._verrou:
            self._arrete = True
            groupes = list(self._actifs)
        if grace > 0:
            echeance = time.monotonic() + grace
            for g in groupes:
                g._fin_grace = echeance
                g.signaler(premier)
        try:
            if grace > 0:
                for g in groupes:
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        g.attendre(max(0, echeance - time.monotonic()))
        finally:
            for g in groupes:
                # La grâce est finie : la récolte n'attend plus personne.
                g._fin_grace = None
                g.signaler(signal.SIGKILL)
        # Récolter : au retour, aucun processus du lot ne vit plus. Borné,
        # un processus en sommeil non interruptible (disque, NFS) ne meurt
        # qu'à son réveil.
        fin = time.monotonic() + RECOLTE_MAX
        for g in groupes:
            with contextlib.suppress(subprocess.TimeoutExpired):
                g.attendre(max(0, fin - time.monotonic()))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.arreter()
        return False
