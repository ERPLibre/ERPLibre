// Une question de TODO (`ask`) en widget natif, selon son genre :
// - text : un champ, le défaut en indication ; Entrée envoie, vide
//   compris, ce qui vaut le défaut comme au CLI ;
// - confirm : Oui et Non, le défaut mis en avant ; y, o et n au clavier,
//   Entrée sur le widget pour le défaut de l'appelant ;
// - typed : un champ ; quand le message porte le texte attendu
//   (`expected`), Confirmer n'est actif qu'à l'égalité exacte. Aucun bouton
//   n'envoie ce texte à la place de l'utilisateur ;
// - secret : un champ masqué, hors de tout formulaire, dont la valeur
//   n'entre jamais dans l'état de la vue : lue à l'envoi, puis effacée ; une
//   valeur que le hub refuserait ne part pas, et le widget le dit ;
// - countdown : la question texte et le temps qui reste, compté depuis
//   l'arrivée du message, qui ne porte pas d'heure : un rechargement, ou un
//   onglet qui reprend la session, le fait repartir de `timeout_s`.
//   L'échéance qui compte est celle du worker, qui prend le défaut et
//   ferme la question ;
// - choose avec `multi` : des cases à cocher et Valider (un choix simple
//   est un menu : MenuView).
// Une confirmation et un choix gardent le champ « Autre réponse ». Chaque
// widget a un nom accessible tiré de `speak`, et Annuler, qui fait ce que
// fait Ctrl+D au terminal : la question finit sans réponse (EOFError,
// Abort sous click), sauf un compte à rebours, où il vaut Entrée et donne
// le défaut. L'Entrée qui valide une composition (IME) ne valide pas le
// champ. Comme MenuView, il répond pour le qid qu'il montre
// (`answer(qid, valeur)`, `cancel(qid)`), jamais dans les ARM ms qui
// suivent son apparition ni d'une touche tenue qui se répète ; le clavier
// va à son champ, ou au widget lui-même, jamais à un bouton qu'une frappe
// d'avance presserait.
import {Component, onMounted, onWillUnmount, useEffect, useRef, useState, xml} from "@odoo/owl";
import {
    ARM,
    choiceValue,
    composing,
    confirmKey,
    keyCounts,
    promptText,
    secondsLeft,
    sendable,
    typedReady,
} from "./prompt.js";

// Rafraîchissement du temps qui reste, en millisecondes.
const TICK = 250;

export class QuestionView extends Component {
    static template = xml`
        <section class="question" role="group" tabindex="-1" t-ref="root"
            t-att-aria-label="props.question.speak or env.t('TODO question')" t-on-keydown="onKey">
            <p t-if="text" class="prompt-text" t-esc="text"/>
            <div t-if="kind === 'confirm'" class="answer-row">
                <button type="button" t-att-class="{default: props.question.default === 'y'}"
                    t-att-disabled="locked" t-on-click="() => this.send('y')" t-esc="env.t('Answer yes')"/>
                <button type="button" t-att-class="{default: props.question.default === 'n'}"
                    t-att-disabled="locked" t-on-click="() => this.send('n')" t-esc="env.t('Answer no')"/>
            </div>
            <div t-elif="kind === 'choose'" class="entries">
                <label t-foreach="options" t-as="option" t-key="option.key" class="entry">
                    <input type="checkbox" t-att-checked="state.picked.includes(option.key)"
                        t-att-disabled="props.pending" t-on-change="() => this.toggle(option.key)"/>
                    <span class="key" t-esc="option.key + '.'"/>
                    <span t-esc="option.label"/>
                </label>
            </div>
            <div t-else="" class="answer-row">
                <input t-if="kind === 'secret'" type="password" class="field" autocomplete="off" t-ref="field"
                    t-att-aria-label="props.question.speak or env.t('Hidden answer')" t-on-keydown="onFieldKey"/>
                <input t-else="" type="text" class="field" autocomplete="off" t-ref="field" t-model="state.value"
                    t-att-placeholder="props.question.default or ''"
                    t-att-aria-label="props.question.speak or env.t('TODO question')" t-on-keydown="onFieldKey"/>
                <span t-if="kind === 'countdown'" class="countdown" role="timer" t-esc="countdownText"/>
                <button type="button" t-att-disabled="locked or !ready" t-on-click="submit" t-esc="submitLabel"/>
                <button type="button" t-att-disabled="locked" t-on-click="cancel" t-esc="env.t('Cancel')"/>
                <span t-if="kind === 'secret'" class="dropped" role="status" t-esc="refusedText"/>
            </div>
            <div t-if="kind === 'confirm' or kind === 'choose'" class="answer-row">
                <button t-if="kind === 'choose'" type="button" t-att-disabled="locked or !state.picked.length"
                    t-on-click="sendPicked" t-esc="env.t('Validate')"/>
                <label class="other">
                    <span t-esc="env.t('Other answer')"/>
                    <input type="text" autocomplete="off" t-model="state.other" t-on-keydown="onOtherKey"/>
                </label>
                <button type="button" t-att-disabled="locked or !canSendOther" t-on-click="sendOther"
                    t-esc="env.t('Send')"/>
                <button type="button" t-att-disabled="locked" t-on-click="cancel" t-esc="env.t('Cancel')"/>
            </div>
        </section>`;

    setup() {
        this.state = useState({value: "", other: "", picked: [], now: Date.now(), armed: false, refused: false});
        this.root = useRef("root");
        this.field = useRef("field");
        this.shownAt = Infinity;
        this.deadline = Date.now() + (this.props.question.timeout_s ?? 0) * 1000;
        // La question prend le clavier quand elle paraît et quand la vue
        // revient.
        useEffect(
            (visible) => {
                if (visible) {
                    this.focus();
                }
            },
            () => [this.props.visible]
        );
        // Ses boutons s'activent ARM ms après qu'elle a paru.
        onMounted(() => {
            this.shownAt = performance.now();
            this.arming = setTimeout(() => (this.state.armed = true), ARM);
            if (this.kind === "countdown") {
                this.ticker = setInterval(() => (this.state.now = Date.now()), TICK);
            }
        });
        onWillUnmount(() => {
            clearTimeout(this.arming);
            clearInterval(this.ticker);
            if (this.kind === "secret" && this.field.el) {
                this.field.el.value = "";
            }
        });
    }

    // Vrai tant que rien ne part : une réponse attend `answered`, ou la
    // question vient de paraître.
    get locked() {
        return this.props.pending || !this.state.armed;
    }

    get kind() {
        return this.props.question.kind;
    }

    get text() {
        return promptText(this.props.question);
    }

    get options() {
        return this.props.question.options ?? [];
    }

    get left() {
        return secondsLeft(this.deadline, this.state.now);
    }

    get countdownText() {
        return this.env.t("Time left: %s s").replace("%s", this.left);
    }

    get submitLabel() {
        return this.kind === "typed" ? this.env.t("Confirm") : this.env.t("Send");
    }

    get refusedText() {
        return this.state.refused ? this.env.t("Hidden answer not sent: a control character, or too long.") : "";
    }

    // Le bouton du champ : une confirmation tapée attend son texte exact ;
    // un secret, dont la valeur n'est pas dans l'état, se vérifie à l'envoi.
    get ready() {
        if (this.kind === "typed") {
            return typedReady(this.props.question, this.state.value);
        }
        return this.kind === "secret" || sendable(this.state.value);
    }

    get canSendOther() {
        return sendable(this.state.other);
    }

    // Le clavier va au champ, sinon au widget : jamais à un bouton, qu'une
    // touche tapée pour la question d'avant presserait.
    focus() {
        (this.field.el ?? this.root.el)?.focus();
    }

    counts(event) {
        return keyCounts(event, this.shownAt);
    }

    send(value) {
        if (!this.locked) {
            this.props.answer(this.props.question.qid, value);
        }
    }

    cancel() {
        if (!this.locked) {
            this.props.cancel(this.props.question.qid);
        }
    }

    // Le champ de la question. Un secret est lu à l'envoi puis effacé : il
    // ne passe que par l'élément, jamais par l'état ; refusé, il ne part pas.
    submit() {
        if (this.locked || !this.ready) {
            return;
        }
        if (this.kind === "secret") {
            const value = this.field.el.value;
            this.field.el.value = "";
            this.state.refused = !sendable(value);
            if (!this.state.refused) {
                this.send(value);
            }
            return;
        }
        this.send(this.state.value);
    }

    onFieldKey(event) {
        if (event.key !== "Enter" || composing(event)) {
            return;
        }
        event.preventDefault();
        if (this.counts(event)) {
            this.submit();
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

    sendOther() {
        if (!this.locked && this.canSendOther) {
            const value = this.state.other;
            this.state.other = "";
            this.send(value);
        }
    }

    toggle(key) {
        const picked = this.state.picked;
        this.state.picked = picked.includes(key) ? picked.filter((other) => other !== key) : [...picked, key];
    }

    sendPicked() {
        if (this.state.picked.length) {
            this.send(choiceValue(this.options, this.state.picked));
        }
    }

    // Confirmation, hors des champs : y, o et n répondent ; Entrée sur le
    // widget lui-même envoie "" : le défaut de l'appelant, comme Entrée au
    // CLI.
    onKey(event) {
        if (this.kind !== "confirm" || this.locked || event.target.tagName === "INPUT") {
            return;
        }
        if (event.ctrlKey || event.altKey || event.metaKey || !this.counts(event)) {
            return;
        }
        const answer = confirmKey(event.key);
        if (answer !== null) {
            event.preventDefault();
            this.send(answer);
        } else if (event.key === "Enter" && event.target === this.root.el) {
            event.preventDefault();
            this.send("");
        }
    }
}
