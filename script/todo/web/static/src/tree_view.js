// Arbre des menus de TODO, avec le compteur de navigation de chaque nœud et
// le bouton ▶ qui le lance dans une session (`launch`, qui reçoit son plan
// de route). Tout vient de /api/telemetry — libellés traduits, chemins,
// compteurs — et des clés de la table de traduction : ce module ne nomme
// aucune commande.
import {Component, useState, xml} from "@odoo/owl";
import {launchRoute} from "./launch.js";
import {filterTree, sortTree} from "./model.js";

export class TreeNode extends Component {
    static template = xml`
        <li t-att-class="props.node.menu ? 'menu' : 'leaf'">
            <button t-if="props.node.menu" type="button" class="toggle"
                t-att-aria-label="props.node.label"
                t-att-aria-expanded="state.open ? 'true' : 'false'"
                t-on-click="toggle" t-esc="state.open ? '▾' : '▸'"/>
            <span class="label" t-esc="props.node.label"/>
            <button t-if="route" type="button" class="launch" t-att-aria-label="launchLabel"
                t-att-title="launchLabel" t-on-click="() => props.launch(route)" t-esc="'▶'"/>
            <span t-if="props.node.section" class="section" t-esc="props.node.section"/>
            <span t-if="props.node.menu or count" class="count" t-esc="count"/>
            <ul t-if="props.node.menu and state.open">
                <t t-foreach="props.node.children" t-as="child" t-key="child_index">
                    <TreeNode node="child" counts="props.counts" depth="props.depth + 1" expand="props.expand"
                        above="nodes" launch="props.launch"/>
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

    // Ce nœud et ceux au-dessus de lui depuis le premier niveau (`above`,
    // null pour la racine) : ce que ses enfants ont au-dessus d'eux.
    get nodes() {
        return this.props.above ? [...this.props.above, this.props.node] : [];
    }

    // Plan de route du nœud, ou null : ni la racine, ni un nœud dont une
    // étape ne peut trouver son entrée ne se lancent.
    get route() {
        return launchRoute(this.nodes);
    }

    get launchLabel() {
        return `${this.env.t("Launch")} ${this.props.node.label}`;
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
            <TreeNode node="shown" counts="props.counts" depth="0" expand="props.query.trim() !== ''"
                above="null" launch="props.launch"/>
        </ul>
        <p t-else="" class="empty" t-esc="env.t('No command found.')"/>`;

    get tree() {
        const found = this.props.tree && filterTree(this.props.tree, this.props.query);
        return found && sortTree(found, this.props.counts, this.props.sort);
    }
}
