// Vue Liste : toutes les feuilles de l'arbre à plat, chacune avec son chemin
// traduit, son compteur et le bouton ▶ qui la lance dans une session
// (`launch`), filtrées par `query` et rangées par `sort`.
import {Component, xml} from "@odoo/owl";
import {launchRoute} from "./launch.js";
import {listRows} from "./model.js";

export class ListView extends Component {
    static template = xml`
        <t t-set="rows" t-value="shown"/>
        <ol t-if="rows.length" class="list">
            <li t-foreach="rows" t-as="row" t-key="row_index">
                <span class="label" t-esc="row.path"/>
                <button t-if="row.route" type="button" class="launch" t-att-aria-label="row.name"
                    t-att-title="row.name" t-on-click="() => props.launch(row.route)" t-esc="'▶'"/>
                <span class="count" t-esc="props.counts[row.node.path] || 0"/>
            </li>
        </ol>
        <p t-else="" class="empty" t-esc="env.t('No command found.')"/>`;

    get shown() {
        if (!this.props.tree) {
            return [];
        }
        const {counts, query, sort} = this.props;
        const launch = this.env.t("Launch");
        return listRows(this.props.tree, counts, query, sort, this.env.lang).map((row) => ({
            ...row,
            route: launchRoute(row.nodes),
            name: `${launch} ${row.path}`,
        }));
    }
}
