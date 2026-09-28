// Un menu de TODO en boutons natifs : le fil d'Ariane, les lignes de son
// écran que ses entrées ne disent pas (une ligne d'état), ou l'invite d'un
// menu lu sur la sortie qui la précède, dont le reste est dans le terminal,
// les titres de section, un bouton « N. libellé » par entrée, l'entrée 0 à
// part, un filtre au-delà de FILTER_FROM entrées, et le champ « Autre
// réponse », qui envoie son texte tel quel. Un choix simple (`ask` de genre
// `choose`) s'y montre aussi : son texte, puis ses options en entrées. Les
// libellés viennent du message, dans la langue de la session : ce module
// ne nomme aucune commande. Au clavier, hors des champs, les touches
// choisissent comme au CLI (`menuKey`) : plusieurs chiffres partent à
// Entrée ou après PAUSE ms.
// Le parent reçoit
// la réponse (`answer(qid, valeur)`) ou l'annulation (`cancel(qid)`, qui
// vaut Ctrl+D), avec le qid de ce menu. Rien ne part tant qu'une réponse
// attend la fin de la question (`pending`), ni dans les ARM ms qui suivent
// l'apparition du menu, ni d'une touche tenue qui se répète : une frappe
// destinée à la question d'avant ne répond pas à celle-ci.
import {Component, onMounted, onWillUnmount, useEffect, useRef, useState, xml} from "@odoo/owl";
import {
    ARM,
    PAUSE,
    backItem,
    composing,
    filterItems,
    keyCounts,
    menuGroups,
    menuKey,
    menuPause,
    menuText,
    sendable,
    showsFilter,
} from "./prompt.js";

export class MenuView extends Component {
    static template = xml`
        <section class="question" role="group" tabindex="-1" t-ref="root"
            t-att-aria-label="props.question.speak or env.t('Menu')" t-on-keydown="onKey">
            <p t-if="crumbs.length" class="crumbs" t-esc="crumbs.join(' › ')"/>
            <p t-if="text" class="prompt-text" t-esc="text"/>
            <input t-if="filtering" type="search" class="filter" t-model="state.query"
                t-att-aria-label="env.t('Filter entries')" t-att-placeholder="env.t('Filter entries')"
                t-on-keydown="onFilterKey"/>
            <t t-foreach="groups" t-as="group" t-key="group_index">
                <h3 t-if="group.section" class="section-title" t-esc="group.section"/>
                <div class="entries">
                    <t t-foreach="group.items" t-as="item" t-key="item.key">
                        <button type="button" class="entry" t-att-class="{danger: item.danger}"
                            t-att-aria-label="item.key + '. ' + (item.speak or item.label)"
                            t-att-disabled="locked" t-on-click="() => this.choose(item.key)">
                            <span class="key" t-esc="item.key + '.'"/>
                            <span t-esc="item.label"/>
                        </button>
                    </t>
                </div>
            </t>
            <p t-if="!groups.length" class="empty" t-esc="env.t('No entry matches the filter.')"/>
            <div class="answer-row">
                <button t-if="back" type="button" class="entry" t-att-disabled="locked"
                    t-att-aria-label="'0. ' + (back.speak or back.label)" t-on-click="() => this.choose('0')">
                    <span class="key" t-esc="'0.'"/>
                    <span t-esc="back.label"/>
                </button>
                <span class="typed" role="status" t-esc="state.typed"/>
                <label class="other">
                    <span t-esc="env.t('Other answer')"/>
                    <input type="text" autocomplete="off" t-model="state.other" t-on-keydown="onOtherKey"/>
                </label>
                <button type="button" t-att-disabled="locked or !canSend" t-on-click="sendOther"
                    t-esc="env.t('Send')"/>
                <button type="button" t-att-disabled="locked" t-on-click="cancel" t-esc="env.t('Cancel')"/>
            </div>
        </section>`;

    setup() {
        this.state = useState({query: "", other: "", typed: "", armed: false});
        this.root = useRef("root");
        this.timer = null;
        this.shownAt = Infinity;
        // Le menu prend le clavier quand il paraît et quand la vue revient.
        useEffect(
            (visible) => {
                if (visible) {
                    this.root.el?.focus();
                }
            },
            () => [this.props.visible]
        );
        // Ses boutons s'activent ARM ms après qu'il a paru.
        onMounted(() => {
            this.shownAt = performance.now();
            this.arming = setTimeout(() => (this.state.armed = true), ARM);
        });
        onWillUnmount(() => {
            clearTimeout(this.timer);
            clearTimeout(this.arming);
        });
    }

    // Vrai tant que rien ne part : une réponse attend `answered`, ou le
    // menu vient de paraître.
    get locked() {
        return this.props.pending || !this.state.armed;
    }

    // Les entrées d'un menu, ou les options d'un choix.
    get items() {
        return this.props.question.items ?? this.props.question.options ?? [];
    }

    get crumbs() {
        return this.props.question.crumbs ?? [];
    }

    // Ce qui se lit au-dessus des entrées (`menuText`) : le texte d'un
    // choix, l'invite d'un menu lu sur la sortie qui la précède, ou les
    // lignes d'un menu qui porte son écran que ses boutons ne disent pas.
    get text() {
        return menuText(this.props.question);
    }

    get keys() {
        return this.items.map((item) => item.key);
    }

    get filtering() {
        return showsFilter(this.items);
    }

    get groups() {
        return menuGroups(filterItems(this.items, this.state.query));
    }

    get back() {
        return backItem(this.items);
    }

    get canSend() {
        return sendable(this.state.other);
    }

    counts(event) {
        return keyCounts(event, this.shownAt);
    }

    // Oublie les chiffres qui attendaient Entrée ou la pause.
    forget() {
        clearTimeout(this.timer);
        this.state.typed = "";
    }

    choose(key) {
        this.forget();
        if (!this.locked) {
            this.props.answer(this.props.question.qid, key);
        }
    }

    cancel() {
        this.forget();
        if (!this.locked) {
            this.props.cancel(this.props.question.qid);
        }
    }

    // Touches du menu hors de ses champs. Ce que `menuKey` ne prend pas —
    // Tab, Espace, Entrée sur un bouton sans rien de tapé — reste au
    // navigateur.
    onKey(event) {
        if (event.target.tagName === "INPUT" || event.ctrlKey || event.altKey || event.metaKey) {
            return;
        }
        if (this.locked || !this.counts(event)) {
            return;
        }
        const before = this.state.typed;
        const {typed, choose} = menuKey(this.keys, before, event.key);
        if (choose === null && typed === before && !(event.key === "Enter" && before)) {
            return;
        }
        event.preventDefault();
        clearTimeout(this.timer);
        this.state.typed = typed;
        if (choose !== null) {
            this.choose(choose);
        } else if (typed) {
            this.timer = setTimeout(() => this.pause(), PAUSE);
        }
    }

    pause() {
        const key = menuPause(this.keys, this.state.typed);
        this.forget();
        if (key !== null) {
            this.choose(key);
        }
    }

    // Entrée dans le filtre choisit l'entrée qu'il laisse seule ; celle qui
    // valide une composition (IME) ne choisit rien.
    onFilterKey(event) {
        if (event.key !== "Enter" || composing(event)) {
            return;
        }
        event.preventDefault();
        const shown = filterItems(this.items, this.state.query);
        if (shown.length === 1 && this.counts(event)) {
            this.choose(shown[0].key);
        }
    }

    onOtherKey(event) {
        if (event.key !== "Enter" || composing(event)) {
            return;
        }
        event.preventDefault();
        if (this.counts(event)) {
            this.sendOther();
        }
    }

    // Le texte du champ, tel quel, vide compris : Entrée au CLI.
    sendOther() {
        if (this.locked || !this.canSend) {
            return;
        }
        const value = this.state.other;
        this.state.other = "";
        this.forget();
        this.props.answer(this.props.question.qid, value);
    }
}
