// Une question de chemin de TODO (`ask` de genre `path`) : le sélecteur de
// la page, là où le terminal montrerait le navigateur urwid. Il part du
// répertoire `start` de la question, que le hub liste (/api/fs) : le fil
// du chemin, cliquable ; « .. » ; les répertoires, puis les fichiers et
// leur taille, ou les répertoires seuls quand TODO en demande un
// (`directory`), avec « Choisir ce répertoire ». Le filtre garde les
// entrées dont le nom le contient. Le champ du chemin suit le répertoire
// montré ; Entrée ou Ouvrir y liste le chemin tapé, ou le répond quand
// c'est un fichier qui existe et que TODO en demande un. Cliquer un
// fichier répond son chemin absolu ; le worker vérifie qu'il existe et
// qu'il est du bon genre, sinon la même question revient. Un chemin que le
// hub ne porterait pas (un caractère de contrôle dans un nom) ne part pas,
// et le widget le dit. Dans la fenêtre bureautique, « Dialogue du
// système » ouvre le dialogue de fichiers du système (`env.desktop`), dont
// le chemin choisi répond de même. Annuler fait ce que fait « q » dans le
// navigateur urwid : rien n'est choisi. Comme les autres widgets, il ne
// répond que pour le qid qu'il montre (`answer(qid, valeur)`,
// `cancel(qid)`), jamais dans les ARM ms qui suivent son apparition ; une
// liste qui arrive après une autre, plus récente, est jetée.
import {Component, onMounted, onWillUnmount, useEffect, useRef, useState, xml} from "@odoo/owl";
import {getJson} from "./api.js";
import {childPath, filterEntries, listingUrl, pathCrumbs, typedOutcome, typedPath} from "./browse.js";
import {formatBytes} from "./metrics.js";
import {ARM, composing, keyCounts, sendable} from "./prompt.js";

export class PathPicker extends Component {
    static template = xml`
        <section class="question path-picker" role="group" tabindex="-1" t-ref="root"
            t-att-aria-label="props.question.speak or env.t('TODO question')">
            <nav class="path-crumbs" t-att-aria-label="env.t('Path')">
                <t t-foreach="crumbs" t-as="crumb" t-key="crumb.path">
                    <button type="button" t-att-disabled="locked" t-on-click="() => this.open(crumb.path)"
                        t-esc="crumb.label"/>
                </t>
            </nav>
            <div class="answer-row">
                <input type="text" class="field" autocomplete="off" spellcheck="false" t-ref="field"
                    t-model="state.typed" t-att-aria-label="env.t('Path')" t-on-keydown="onFieldKey"/>
                <button type="button" t-att-disabled="locked or !state.typed.trim()" t-on-click="openTyped"
                    t-esc="env.t('Open')"/>
                <button t-if="directory" type="button" t-att-disabled="locked or !here or listing.error"
                    t-on-click="() => this.send(here)" t-esc="env.t('Choose this directory')"/>
                <button t-if="state.canPick" type="button" t-att-disabled="locked" t-on-click="systemDialog"
                    t-esc="env.t('System dialog')"/>
                <button type="button" t-att-disabled="locked" t-on-click="cancel" t-esc="env.t('Cancel')"/>
            </div>
            <input type="search" class="filter" t-model="state.filter" t-att-aria-label="env.t('Filter entries')"
                t-att-placeholder="env.t('Filter entries')"/>
            <p t-if="listing.error" class="dropped" role="status" t-esc="errorText"/>
            <p t-if="state.refused" class="dropped" role="status"
                t-esc="env.t('Path not sent: a control character, or too long.')"/>
            <ul class="path-entries">
                <li t-if="listing.parent">
                    <button type="button" class="entry" t-att-disabled="locked"
                        t-att-aria-label="env.t('Parent directory')" t-on-click="() => this.open(listing.parent)"
                        t-esc="'..'"/>
                </li>
                <li t-foreach="entries" t-as="entry" t-key="entry.name">
                    <button type="button" class="entry" t-att-class="{dir: entry.dir}" t-att-disabled="locked"
                        t-on-click="() => this.pick(entry)">
                        <span t-esc="entry.dir ? entry.name + '/' : entry.name"/>
                        <span t-if="!entry.dir and entry.size !== null" class="size" t-esc="sizeText(entry.size)"/>
                    </button>
                </li>
            </ul>
            <p t-if="missed" class="empty" t-esc="env.t('No entry matches the filter.')"/>
            <p t-if="listing.truncated" class="dropped" role="status" t-esc="truncatedText"/>
        </section>`;

    setup() {
        const start = this.props.question.start ?? "~";
        // Le pont de la fenêtre bureautique peut n'arriver qu'après la
        // question, avec `pywebviewready`.
        const canPick = this.env.desktop.canPick();
        this.state = useState({listing: null, typed: start, filter: "", armed: false, refused: false, canPick});
        this.onReady = () => (this.state.canPick = this.env.desktop.canPick());
        this.root = useRef("root");
        this.field = useRef("field");
        this.shownAt = Infinity;
        this.ticket = 0;
        // Le widget prend le clavier quand il paraît et quand la vue revient.
        useEffect(
            (visible) => {
                if (visible) {
                    this.field.el?.focus();
                }
            },
            () => [this.props.visible]
        );
        onMounted(() => {
            this.shownAt = performance.now();
            this.arming = setTimeout(() => (this.state.armed = true), ARM);
            window.addEventListener("pywebviewready", this.onReady);
            this.open(start);
        });
        onWillUnmount(() => {
            clearTimeout(this.arming);
            window.removeEventListener("pywebviewready", this.onReady);
        });
    }

    // Vrai tant que rien ne part : une réponse attend `answered`, ou le
    // widget vient de paraître.
    get locked() {
        return this.props.pending || !this.state.armed;
    }

    get directory() {
        return this.props.question.directory === true;
    }

    // Le répertoire montré ; vide avant la première liste.
    get listing() {
        return this.state.listing ?? {path: "", parent: null, entries: [], truncated: false};
    }

    // Le répertoire montré, s'il s'est listé : là où « Choisir ce
    // répertoire » répond.
    get here() {
        return this.listing.path;
    }

    get crumbs() {
        return this.here ? pathCrumbs(this.here) : [];
    }

    get entries() {
        return filterEntries(this.listing.entries, this.state.filter);
    }

    get missed() {
        return Boolean(this.state.filter.trim()) && this.listing.entries.length > 0 && !this.entries.length;
    }

    get errorText() {
        return this.env.t("Cannot list this directory: %s").replace("%s", () => this.listing.error);
    }

    get truncatedText() {
        return this.env.t("Only the first %s entries are shown.").replace("%s", this.listing.entries.length);
    }

    sizeText(size) {
        return formatBytes(size, this.env.lang);
    }

    // Liste `path` ; tapé (`typed`), un fichier qui existe répond quand
    // TODO en demande un. Seule la dernière demande se montre.
    async open(path, typed = false) {
        const ticket = ++this.ticket;
        let listing;
        try {
            listing = await getJson(listingUrl(path, this.directory), {csrf: true});
        } catch (error) {
            listing = {path, parent: null, entries: [], truncated: false, error: error.message, file: false};
        }
        if (ticket !== this.ticket) {
            return;
        }
        const outcome = typed ? typedOutcome(listing, this.directory) : {show: listing};
        if (outcome.answer) {
            this.send(outcome.answer);
            return;
        }
        Object.assign(this.state, {listing: outcome.show, typed: outcome.show.path, filter: "", refused: false});
    }

    openTyped() {
        const path = typedPath(this.here || "/", this.state.typed);
        if (path !== null && !this.locked) {
            this.open(path, true);
        }
    }

    // Une entrée : un répertoire s'ouvre, un fichier répond.
    pick(entry) {
        const path = childPath(this.here, entry.name);
        if (entry.dir) {
            this.open(path);
        } else {
            this.send(path);
        }
    }

    // Le dialogue de fichiers du système, ouvert sur le répertoire montré :
    // le chemin choisi répond, comme un clic dans la liste.
    async systemDialog() {
        if (this.locked) {
            return;
        }
        const chosen = await this.env.desktop.pickPath(this.here || this.props.question.start, this.directory);
        if (chosen) {
            this.send(chosen);
        }
    }

    send(value) {
        if (this.locked) {
            return;
        }
        this.state.refused = !sendable(value);
        if (!this.state.refused) {
            this.props.answer(this.props.question.qid, value);
        }
    }

    cancel() {
        if (!this.locked) {
            this.props.cancel(this.props.question.qid);
        }
    }

    onFieldKey(event) {
        if (event.key !== "Enter" || composing(event)) {
            return;
        }
        event.preventDefault();
        if (keyCounts(event, this.shownAt)) {
            this.openTyped();
        }
    }
}
