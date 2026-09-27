// Page de télémétrie : une barre d'outils (vues, recherche, tri) au-dessus de
// la vue choisie. La vue et le tri vivent dans le fragment de l'URL, qu'un
// rechargement retrouve ; la recherche n'y entre pas. Une vue qui n'offre
// aucun tri n'offre pas de recherche non plus. Les libellés viennent de
// `env.t`, la table de traduction de la page.
import {Component, useState, xml} from "@odoo/owl";
import {ListView} from "./list_view.js";
import {SORTS, VIEWS, effectiveSort, readFragment, writeFragment} from "./model.js";
import {SystemView} from "./system_view.js";
import {TreeView} from "./tree_view.js";

const VIEW_LABELS = {tree: "Tree", list: "List", system: "System"};
const SORT_LABELS = {code: "Code order", usage: "Most used", name: "Name"};

export class TelemetryPage extends Component {
    static components = {ListView, SystemView, TreeView};
    static template = xml`
        <header class="bar">
            <h1 t-esc="env.t('TODO navigation telemetry')"/>
            <span class="root" t-esc="props.root"/>
        </header>
        <nav class="toolbar" t-att-aria-label="env.t('Views')">
            <t t-foreach="views" t-as="view" t-key="view">
                <button type="button" t-att-aria-pressed="state.view === view ? 'true' : 'false'"
                    t-on-click="() => this.show(view)" t-esc="env.t(viewLabels[view])"/>
            </t>
            <t t-if="sorts.length">
                <input type="search" class="search" t-model="state.query"
                    t-att-placeholder="env.t('Search')" t-att-aria-label="env.t('Search')"/>
                <label class="sort">
                    <t t-esc="env.t('Sort')"/>
                    <select t-on-change="(ev) => this.sortBy(ev.target.value)">
                        <t t-foreach="sorts" t-as="option" t-key="option">
                            <option t-att-value="option" t-att-selected="option === sort"
                                t-esc="env.t(sortLabels[option])"/>
                        </t>
                    </select>
                </label>
            </t>
        </nav>
        <p class="summary" t-esc="summary"/>
        <TreeView t-if="state.view === 'tree'" t-key="sort + '|' + state.query" tree="tree" counts="counts"
            query="state.query" sort="sort"/>
        <ListView t-elif="state.view === 'list'" tree="tree" counts="counts" query="state.query" sort="sort"/>
        <SystemView t-else=""/>`;

    setup() {
        this.views = VIEWS;
        this.viewLabels = VIEW_LABELS;
        this.sortLabels = SORT_LABELS;
        this.state = useState({...readFragment(window.location.hash), query: ""});
    }

    get tree() {
        return this.props.telemetry.tree;
    }

    get counts() {
        return this.props.telemetry.counts;
    }

    get sorts() {
        return SORTS[this.state.view] || [];
    }

    get sort() {
        return effectiveSort(this.state.view, this.state.sort);
    }

    get summary() {
        const counts = Object.values(this.counts);
        const total = counts.reduce((sum, n) => sum + n, 0);
        const source = this.tree ? this.env.t("tree from code") : this.env.t("visited paths only");
        return `${total} ${this.env.t("navigations")} · ${counts.length} ${this.env.t("menus")} · ${source}`;
    }

    // Réécrit le fragment sans nouvelle entrée d'historique.
    remember() {
        const {view, sort} = this.state;
        history.replaceState(null, "", writeFragment(window.location.hash, {view, sort}));
    }

    show(view) {
        this.state.view = view;
        this.remember();
    }

    sortBy(sort) {
        this.state.sort = sort;
        this.remember();
    }
}
