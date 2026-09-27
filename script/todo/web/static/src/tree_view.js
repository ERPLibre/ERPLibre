// Arbre des menus de TODO, avec le compteur de navigation de chaque nœud.
// Tout vient de /api/telemetry — libellés traduits, chemins, compteurs — et
// des clés de la table de traduction : ce module ne nomme aucune commande.
import {Component, useState, xml} from "@odoo/owl";

export class TreeNode extends Component {
    static template = xml`
        <li t-att-class="props.node.menu ? 'menu' : 'leaf'">
            <button t-if="props.node.menu" type="button" class="toggle"
                t-att-aria-label="props.node.label"
                t-att-aria-expanded="state.open ? 'true' : 'false'"
                t-on-click="toggle" t-esc="state.open ? '▾' : '▸'"/>
            <span class="label" t-esc="props.node.label"/>
            <span t-if="props.node.section" class="section" t-esc="props.node.section"/>
            <span t-if="props.node.menu or count" class="count" t-esc="count"/>
            <ul t-if="props.node.menu and state.open">
                <t t-foreach="props.node.children" t-as="child" t-key="child_index">
                    <TreeNode node="child" counts="props.counts" depth="props.depth + 1"/>
                </t>
            </ul>
        </li>`;

    setup() {
        // Racine et premier niveau ouverts : les familles de menus d'un coup d'œil.
        this.state = useState({open: this.props.depth < 2});
    }

    get count() {
        return this.props.counts[this.props.node.path] || 0;
    }

    toggle() {
        this.state.open = !this.state.open;
    }
}
TreeNode.components = {TreeNode};

export class TelemetryPage extends Component {
    static components = {TreeNode};
    static template = xml`
        <header class="bar">
            <h1 t-esc="t('TODO navigation telemetry')"/>
            <span class="root" t-esc="props.root"/>
        </header>
        <p class="summary" t-esc="summary"/>
        <ul t-if="props.telemetry.tree" class="tree">
            <TreeNode node="props.telemetry.tree" counts="props.telemetry.counts" depth="0"/>
        </ul>`;

    t(key) {
        return this.props.terms[key] ?? key;
    }

    get summary() {
        const counts = Object.values(this.props.telemetry.counts);
        const total = counts.reduce((sum, n) => sum + n, 0);
        const source = this.props.telemetry.tree ? this.t("tree from code") : this.t("visited paths only");
        return `${total} ${this.t("navigations")} · ${counts.length} ${this.t("menus")} · ${source}`;
    }
}
