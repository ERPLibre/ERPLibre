// Arbre des menus de TODO, avec le compteur de navigation de chaque nœud.
// Tout vient de /api/telemetry — libellés traduits, chemins, compteurs — et
// des clés de la table de traduction : ce module ne nomme aucune commande.
import {Component, useState, xml} from "@odoo/owl";
import {filterTree, sortTree} from "./model.js";

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
                    <TreeNode node="child" counts="props.counts" depth="props.depth + 1" expand="props.expand"/>
                </t>
            </ul>
        </li>`;

    setup() {
        // Racine et premier niveau ouverts : les familles de menus d'un coup
        // d'œil. Pendant une recherche (`expand`), tout ce qui reste l'est.
        this.state = useState({open: this.props.expand || this.props.depth < 2});
    }

    get count() {
        return this.props.counts[this.props.node.path] || 0;
    }

    toggle() {
        this.state.open = !this.state.open;
    }
}
TreeNode.components = {TreeNode};

// Vue Arbre : l'arbre filtré par `query`, rangé par `sort`.
export class TreeView extends Component {
    static components = {TreeNode};
    static template = xml`
        <t t-set="shown" t-value="tree"/>
        <ul t-if="shown" class="tree">
            <TreeNode node="shown" counts="props.counts" depth="0" expand="props.query.trim() !== ''"/>
        </ul>
        <p t-else="" class="empty" t-esc="env.t('No command found.')"/>`;

    get tree() {
        const found = this.props.tree && filterTree(this.props.tree, this.props.query);
        return found && sortTree(found, this.props.counts, this.props.sort);
    }
}
