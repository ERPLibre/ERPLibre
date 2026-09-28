// Vue Sessions : le vrai TODO dans un terminal xterm.js, relié par /ws à une
// session du hub. La barre dit la session et son état ; Arrêter envoie
// `interrupt`, qui n'arrête que ce que TODO a lancé, Fermer `close`. Ctrl+C
// au clavier reste l'octet du terminal. L'identifiant vit dans le
// fragment : un rechargement s'y rattache, et le hub rejoue la sortie que
// son anneau garde. La vue reste montée, cachée, quand une autre s'affiche :
// la session ne se détache pas. Ce module ne nomme aucune commande.
//
// Un menu de TODO (`menu`) et un choix simple s'affichent au-dessus du
// terminal en boutons natifs (MenuView), toute autre question en widget
// selon son genre (QuestionView) ; répondre par eux ou par le terminal
// revient au même : le worker prend la première réponse, puis `answered`
// ferme le widget. Un genre que la page ne connaît pas reste au terminal.
// Le terminal se replie sous un menu dont les boutons tiennent tout
// l'écran (`carriesScreen`) ; il reste montré sous toute autre question, dont
// le contexte n'est que là, tant que ce que TODO a écrit depuis la dernière
// réponse reste à lire (la sortie d'une commande, un avis du worker, ce
// qu'un menu dit avoir au-dessus de lui : `stillToRead`), pendant une
// commande, en écran alternatif et à l'invite d'un programme
// (`terminalShown`). Le bouton Terminal l'ouvre ou le ferme pour la phase
// en cours.
//
// L'état du terminal vient du hub (`tty_state`), jamais du texte : l'écho
// coupé en mode canonique ouvre un champ masqué, dont la valeur part au
// terminal et n'est gardée nulle part ; un processus qui lit le terminal
// fait proposer les réponses de l'invite qui finit l'écran ; l'écran
// alternatif agrandit le panneau à la fenêtre, jusqu'à ce que le bouton
// « Plein écran », relâché, rende la page. Le hub ignore les frappes que
// rien ne lit, sauf en mode brut, et dit ce qu'il a jeté, et pourquoi
// (`dropped`).
import {Component, onMounted, onWillUnmount, useEffect, useRef, useState, xml} from "@odoo/owl";
import {getJson} from "./api.js";
import {MenuView} from "./menu_view.js";
import {ASK_KINDS, answerable} from "./prompt.js";
import {QuestionView} from "./question_view.js";
import {
    asksSecret,
    closedState,
    foldPhase,
    frames,
    heldOverride,
    helloMessage,
    joinWrapped,
    lastLine,
    quickAnswers,
    sessionOf,
    stillToRead,
    terminalShown,
    withSession,
} from "./session.js";

const PERIOD = 2000;
// Durée d'un avis de trame ignorée, en millisecondes.
const NOTICE = 3000;
// Avis de ce que le hub n'a pas écrit (`dropped`), selon sa raison ; une
// raison inconnue vaut `unread`.
const DROP_LABELS = {
    unread: "Nothing reads the terminal: keystrokes ignored.",
    question: "A new prompt began: pending keystrokes were not sent.",
    stop: "Stopped: pending keystrokes were thrown away.",
    secret: "The prompt ended: the hidden answer was not sent.",
    detached: "Keystrokes pending while no tab was open were thrown away.",
};
// Lignes relues au-dessus du curseur pour trouver la dernière non vide.
const LOOKBACK = 4;
const TTY = {echo: true, canon: true, reader: null, altscreen: false};
const STATE_LABELS = {
    connecting: "Connecting…",
    ended: "Session ended",
    full: "Too many sessions: close one first.",
    taken: "Opened in another tab.",
    gone: "This session no longer exists.",
    lost: "Connection lost.",
};

export class SessionsView extends Component {
    static components = {MenuView, QuestionView};
    static template = xml`
        <section class="sessions"
            t-att-class="{fullscreen: state.status === 'open' and state.tty.altscreen and !state.windowed}"
            t-att-hidden="props.visible ? undefined : 'hidden'">
            <nav class="toolbar" t-att-aria-label="env.t('Sessions')">
                <button type="button" t-on-click="() => this.connect(null)" t-esc="env.t('Open a TODO session')"/>
                <t t-foreach="state.list" t-as="item" t-key="item.id">
                    <button type="button" t-att-aria-pressed="item.id === state.id ? 'true' : 'false'"
                        t-on-click="() => this.connect(item.id)"
                        t-esc="item.running ? item.id + ' · ' + env.t('running') : item.id"/>
                </t>
            </nav>
            <div t-if="state.id or state.status" class="toolbar session-bar">
                <code t-esc="state.id"/>
                <span class="state" t-esc="stateText"/>
                <t t-if="state.status === 'open'">
                    <button type="button" t-on-click="() => this.send({t: 'interrupt'})" t-esc="env.t('Stop')"/>
                    <button type="button" t-on-click="() => this.send({t: 'close'})" t-esc="env.t('Close')"/>
                    <button type="button" t-att-aria-pressed="state.raw ? 'true' : 'false'" t-on-click="toggleRaw"
                        t-esc="env.t('Raw mode')"/>
                    <button type="button" aria-controls="session-terminal"
                        t-att-aria-expanded="terminalOpen ? 'true' : 'false'" t-on-click="toggleTerminal"
                        t-esc="env.t('Terminal')"/>
                    <button t-if="state.tty.altscreen" type="button"
                        t-att-aria-pressed="state.windowed ? 'false' : 'true'" t-on-click="toggleWindowed"
                        t-esc="env.t('Full screen')"/>
                    <span t-if="state.notice" class="dropped" role="status" t-esc="noticeText"/>
                </t>
                <button t-elif="state.id and ['taken', 'lost'].includes(state.status)" type="button"
                    t-on-click="() => this.connect(state.id, this.offset)" t-esc="env.t('Reconnect')"/>
            </div>
            <div t-if="secret" class="toolbar secret">
                <label>
                    <t t-esc="env.t('Hidden answer')"/>
                    <input type="password" autocomplete="off" aria-describedby="secret-prompt" t-ref="secret"
                        t-on-keydown="onSecretKey"/>
                </label>
                <span id="secret-prompt" class="visually-hidden" t-esc="state.prompt"/>
                <button type="button" t-on-click="sendSecret" t-esc="env.t('Send')"/>
            </div>
            <div t-if="state.status === 'open' and state.answers.length and !structured" class="toolbar" role="group"
                t-att-aria-label="env.t('Quick answers')">
                <t t-foreach="state.answers" t-as="answer" t-key="answer">
                    <button type="button" t-on-click="() => this.answer(answer)" t-esc="answer"/>
                </t>
            </div>
            <div t-if="structured" class="prompt-panel">
                <MenuView t-if="structured.t === 'menu' or (structured.kind === 'choose' and !structured.multi)"
                    t-key="structured.qid" question="structured" pending="state.pending === structured.qid"
                    visible="props.visible" answer.bind="reply" cancel.bind="cancel"/>
                <QuestionView t-else="" t-key="structured.qid" question="structured"
                    pending="state.pending === structured.qid" visible="props.visible"
                    answer.bind="reply" cancel.bind="cancel"/>
            </div>
            <div id="session-terminal" class="terminal" t-ref="terminal"
                t-att-hidden="terminalOpen ? undefined : 'hidden'"/>
        </section>`;

    setup() {
        this.state = useState({
            list: [],
            id: sessionOf(window.location.hash),
            status: null,
            code: null,
            tty: {...TTY},
            answers: [],
            prompt: "",
            raw: false,
            windowed: false,
            notice: "",
            question: null, // la dernière question du worker, jusqu'à `answered`
            pending: null, // le qid auquel la page a répondu
            running: false, // entre `run_start` et `run_end`
            ran: false, // ce que TODO a écrit depuis la dernière réponse reste à lire
            override: null, // le choix du bouton Terminal : {phase, open}
        });
        this.panel = useRef("terminal");
        this.secretField = useRef("secret");
        // Le champ masqué prend le clavier dès qu'il paraît, et quand la vue
        // revient ; parti, lui ou le widget d'une question, le clavier revient
        // au terminal si personne ne l'a pris.
        useEffect(
            (field, visible) => {
                if (field && visible) {
                    field.focus();
                } else if (!field && document.activeElement === document.body) {
                    this.term?.focus();
                }
            },
            () => [this.secretField.el, this.props.visible, this.structured?.qid]
        );
        // Un gestionnaire de mots de passe peut proposer d'enregistrer ce
        // que garde un champ masqué quand la page s'en va, formulaire ou non,
        // `autocomplete="off"` n'y changeant rien : ces champs se vident
        // avant.
        this.onPageHide = () => {
            for (const field of document.querySelectorAll("input[type=password]")) {
                field.value = "";
            }
        };
        window.addEventListener("pagehide", this.onPageHide);
        this.socket = null;
        this.bye = null;
        this.offset = 0; // décalage absolu du prochain octet attendu
        this.encoder = new TextEncoder();
        onMounted(() => {
            // Scripts classiques chargés par index.html : des globales.
            this.term = new globalThis.Terminal({fontFamily: "ui-monospace, monospace"});
            this.fit = new globalThis.FitAddon.FitAddon();
            this.term.loadAddon(this.fit);
            this.term.open(this.panel.el);
            this.term.onData((data) => this.type(data));
            this.term.onResize(({cols, rows}) => this.send({t: "resize", cols, rows}));
            this.resizer = new ResizeObserver(() => this.fit.fit());
            this.resizer.observe(this.panel.el);
            this.fit.fit();
            this.timer = setInterval(() => this.poll(), PERIOD);
            this.poll();
            if (this.state.id) {
                this.connect(this.state.id);
            }
        });
        onWillUnmount(() => {
            window.removeEventListener("pagehide", this.onPageHide);
            clearInterval(this.timer);
            clearTimeout(this.noticeTimer);
            this.resizer.disconnect();
            this.drop();
            this.term.dispose();
        });
    }

    // Le champ masqué de TtyWatch, pour l'invite d'un programme : une
    // question du worker a son propre widget.
    get secret() {
        return this.state.status === "open" && asksSecret(this.state.tty) && !this.structured;
    }

    // Ce dont dépend le repli du terminal.
    get fold() {
        const {running, ran, tty} = this.state;
        return {question: this.structured, running, altscreen: tty.altscreen, ran, tty};
    }

    get terminalOpen() {
        return terminalShown({...this.fold, override: this.state.override});
    }

    // La question du worker que la page montre en widget, ou null.
    get structured() {
        const question = this.state.question;
        const shown = question?.t === "menu" || (question?.t === "ask" && ASK_KINDS.includes(question.kind));
        return this.state.status === "open" && shown ? question : null;
    }

    get noticeText() {
        return this.state.notice ? this.env.t(DROP_LABELS[this.state.notice]) : "";
    }

    get stateText() {
        const {status, code} = this.state;
        if (!STATE_LABELS[status]) {
            return "";
        }
        const label = this.env.t(STATE_LABELS[status]);
        return status === "ended" ? `${label} (${this.env.t("exit code")} ${code})` : label;
    }

    // Ouvre une session (`id` null) ou s'y rattache ; `after` > 0 garde
    // l'écran et ne demande que la suite.
    connect(id, after = 0) {
        this.drop();
        if (!after) {
            this.term.reset();
        }
        this.bye = null;
        // Le mode brut vaut pour une session : il ne suit pas vers une autre.
        const raw = Boolean(id) && id === this.state.id && this.state.raw;
        Object.assign(this.state, {id, status: "connecting", code: null, tty: {...TTY}, answers: [], raw});
        Object.assign(this.state, {prompt: "", windowed: false, notice: "", question: null, pending: null});
        Object.assign(this.state, {running: false, ran: false, override: null});
        const socket = new WebSocket(`ws://${window.location.host}/ws`);
        socket.binaryType = "arraybuffer";
        socket.onopen = () => {
            const {cols, rows} = this.term;
            const {csrf, lang} = this.env;
            socket.send(helloMessage({csrf, lang, cols, rows, session: id, after}));
        };
        socket.onmessage = (event) => socket === this.socket && this.receive(event.data);
        socket.onclose = (event) => socket === this.socket && this.closed(event.code);
        this.socket = socket;
        this.term.focus();
    }

    // Ferme la connexion courante sans rien changer à l'état affiché.
    drop() {
        const socket = this.socket;
        this.socket = null;
        socket?.close();
    }

    receive(data) {
        if (typeof data !== "string") {
            const bytes = new Uint8Array(data);
            this.offset += bytes.length;
            this.term.write(bytes, () => this.refreshAnswers());
            return;
        }
        const message = JSON.parse(data);
        if (message.t === "session") {
            // La question ouverte, s'il y en a une, suit ce message.
            this.offset = message.offset;
            Object.assign(this.state, {id: message.id, status: "open", question: null, pending: null});
            Object.assign(this.state, {running: false, ran: false});
            this.remember(message.id);
            if (message.truncated) {
                this.term.write(`\r\n[${this.env.t("Output truncated")}]\r\n`);
            }
            if (this.state.raw) {
                this.send({t: "raw", on: true});
            }
        } else if (message.t === "tty_state") {
            const {echo, canon, reader, altscreen} = message;
            this.state.tty = {echo, canon, reader, altscreen};
            if (!altscreen) {
                this.state.windowed = false;
            }
            this.refreshAnswers();
        } else if (message.t === "menu" || message.t === "ask") {
            Object.assign(this.state, {question: message, pending: null});
        } else if (message.t === "answered") {
            if (this.state.question?.qid === message.qid) {
                Object.assign(this.state, {question: null, pending: null});
            }
        } else if (message.t === "run_start" || message.t === "run_end") {
            this.state.running = message.t === "run_start";
        } else if (message.t === "dropped") {
            this.state.notice = Object.hasOwn(DROP_LABELS, message.reason) ? message.reason : "unread";
            clearTimeout(this.noticeTimer);
            this.noticeTimer = setTimeout(() => (this.state.notice = ""), NOTICE);
        } else if (message.t === "bye") {
            this.bye = message;
            this.state.code = message.code;
        } else if (message.t === "open_view") {
            this.props.openView(message.view);
        }
        this.state.ran = stillToRead(this.state.ran, message);
        // Le choix du bouton Terminal s'oublie dès que sa phase change.
        if (this.state.override) {
            this.state.override = heldOverride(this.state.override, foldPhase(this.fold));
        }
    }

    closed(code) {
        this.socket = null;
        const status = closedState(code, this.bye);
        Object.assign(this.state, {status, question: null, pending: null});
        Object.assign(this.state, {running: false, ran: false, override: null});
        if (status === "ended" || status === "gone") {
            this.remember(null);
        }
        this.poll();
    }

    remember(id) {
        history.replaceState(null, "", withSession(window.location.hash, id));
    }

    send(message) {
        if (this.socket?.readyState === WebSocket.OPEN && this.state.status === "open") {
            this.socket.send(JSON.stringify(message));
        }
    }

    // La réponse de la page à la question `qid`, ou son annulation, qui
    // vaut Ctrl+D : une seule part par question, et seulement tant que
    // `qid` est la question ouverte (`answerable`).
    settle(qid, message) {
        if (answerable(this.state.question, this.state.pending, qid)) {
            this.state.pending = qid;
            this.send({...message, qid});
        }
    }

    reply(qid, value) {
        this.settle(qid, {t: "answer", value});
    }

    cancel(qid) {
        this.settle(qid, {t: "cancel"});
    }

    // Frappes et collages : des octets UTF-8, en trames binaires.
    type(data) {
        if (this.socket?.readyState === WebSocket.OPEN && this.state.status === "open") {
            for (const frame of frames(this.encoder.encode(data))) {
                this.socket.send(frame);
            }
        }
    }

    // La dernière ligne non vide jusqu'au curseur, rangées coupées par le
    // terminal rejointes : l'invite, que décrit le champ masqué. Réponses
    // rapides : celles qu'elle propose, quand un processus lit le terminal
    // hors de l'écran alternatif, où la ligne du curseur n'est pas une
    // invite.
    refreshAnswers() {
        const buffer = this.term.buffer.active;
        const end = buffer.baseY + buffer.cursorY;
        const rows = [];
        for (let y = Math.max(0, end - LOOKBACK); y <= end; y++) {
            const line = buffer.getLine(y);
            rows.push({text: line?.translateToString(false) ?? "", wrapped: Boolean(line?.isWrapped)});
        }
        const prompt = lastLine(joinWrapped(rows));
        const {reader, altscreen} = this.state.tty;
        const answers = reader === true && !altscreen ? quickAnswers(prompt) : [];
        if (prompt !== this.state.prompt) {
            this.state.prompt = prompt;
        }
        if (answers.join("/") !== this.state.answers.join("/")) {
            this.state.answers = answers;
        }
    }

    answer(value) {
        this.state.answers = [];
        this.type(`${value}\r`);
        this.term.focus();
    }

    // La valeur part au terminal, suivie de Entrée, et le champ se vide :
    // elle n'entre ni dans l'état de la vue ni ailleurs. `secret` annonce
    // au hub que la trame suivante est cette réponse : il ne l'écrit que si
    // l'écho est encore coupé, pour qu'elle ne s'affiche jamais.
    sendSecret() {
        const field = this.secretField.el;
        if (this.secret) {
            this.send({t: "secret"});
            this.type(`${field.value}\r`);
        }
        field.value = "";
    }

    // Entrée envoie ; Échap rend le clavier au terminal. Sans formulaire, un
    // gestionnaire de mots de passe n'a rien à enregistrer.
    onSecretKey(event) {
        if (event.key === "Enter") {
            event.preventDefault();
            this.sendSecret();
        } else if (event.key === "Escape") {
            this.term.focus();
        }
    }

    toggleRaw() {
        this.state.raw = !this.state.raw;
        this.send({t: "raw", on: this.state.raw});
        this.term.focus();
    }

    // Ouvre ou ferme le terminal jusqu'au changement de phase : une autre
    // question, une commande qui commence ou finit, l'écran alternatif.
    toggleTerminal() {
        this.state.override = {phase: foldPhase(this.fold), open: !this.terminalOpen};
    }

    // Plein écran pressé : la vue couvre la fenêtre ; relâché, la page et
    // ses vues restent à portée pendant l'écran alternatif.
    toggleWindowed() {
        this.state.windowed = !this.state.windowed;
        this.term.focus();
    }

    // Liste des sessions, tant que la vue se voit.
    async poll() {
        if (!this.props.visible || document.visibilityState !== "visible") {
            return;
        }
        try {
            this.state.list = (await getJson("/api/sessions")).sessions;
        } catch {
            this.state.list = [];
        }
    }
}
