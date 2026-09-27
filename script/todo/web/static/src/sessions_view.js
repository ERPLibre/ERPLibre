// Vue Sessions : le vrai TODO dans un terminal xterm.js, relié par /ws à une
// session du hub. La barre dit la session et son état ; Arrêter envoie
// `interrupt`, qui n'arrête que ce que TODO a lancé, Fermer `close`. Ctrl+C
// au clavier reste l'octet du terminal. L'identifiant vit dans le
// fragment : un rechargement s'y rattache, et le hub rejoue la sortie que
// son anneau garde. La vue reste montée, cachée, quand une autre s'affiche :
// la session ne se détache pas. Ce module ne nomme aucune commande.
import {Component, onMounted, onWillUnmount, useRef, useState, xml} from "@odoo/owl";
import {getJson} from "./api.js";
import {closedState, frames, helloMessage, sessionOf, withSession} from "./session.js";

const PERIOD = 2000;
const STATE_LABELS = {
    connecting: "Connecting…",
    ended: "Session ended",
    full: "Too many sessions: close one first.",
    taken: "Opened in another tab.",
    gone: "This session no longer exists.",
    lost: "Connection lost.",
};

export class SessionsView extends Component {
    static template = xml`
        <section class="sessions" t-att-hidden="props.visible ? undefined : 'hidden'">
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
                </t>
                <button t-elif="state.id and ['taken', 'lost'].includes(state.status)" type="button"
                    t-on-click="() => this.connect(state.id, this.offset)" t-esc="env.t('Reconnect')"/>
            </div>
            <div class="terminal" t-ref="terminal"/>
        </section>`;

    setup() {
        this.state = useState({list: [], id: sessionOf(window.location.hash), status: null, code: null});
        this.panel = useRef("terminal");
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
            clearInterval(this.timer);
            this.resizer.disconnect();
            this.drop();
            this.term.dispose();
        });
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
        Object.assign(this.state, {id, status: "connecting", code: null});
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
            this.term.write(bytes);
            return;
        }
        const message = JSON.parse(data);
        if (message.t === "session") {
            this.offset = message.offset;
            Object.assign(this.state, {id: message.id, status: "open"});
            this.remember(message.id);
            if (message.truncated) {
                this.term.write(`\r\n[${this.env.t("Output truncated")}]\r\n`);
            }
        } else if (message.t === "bye") {
            this.bye = message;
            this.state.code = message.code;
        } else if (message.t === "open_view") {
            this.props.openView(message.view);
        }
    }

    closed(code) {
        this.socket = null;
        const status = closedState(code, this.bye);
        this.state.status = status;
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

    // Frappes et collages : des octets UTF-8, en trames binaires.
    type(data) {
        if (this.socket?.readyState === WebSocket.OPEN && this.state.status === "open") {
            for (const frame of frames(this.encoder.encode(data))) {
                this.socket.send(frame);
            }
        }
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
