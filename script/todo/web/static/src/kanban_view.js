// Vue Kanban : une colonne par menu qui porte des feuilles, avec le compteur
// du menu ; une carte par feuille, avec son compteur et le bouton ▶ qui la
// lance dans une session (`launch`). Recherche et tri sont ceux de la Liste
// (`kanbanColumns`) ; les colonnes défilent de côté. Tout vient de
// /api/telemetry : ce module ne nomme aucune commande.
import {Component, xml} from "@odoo/owl";
import {launchRoute} from "./launch.js";
import {kanbanColumns} from "./model.js";

export class KanbanView extends Component {
    static template = xml`
        <t t-set="columns" t-value="shown"/>
        <div t-if="columns.length" class="kanban">
            <section t-foreach="columns" t-as="column" t-key="column_index" class="column">
                <h2>
                    <span t-esc="column.path"/>
                    <span class="count" t-esc="props.counts[column.node.path] || 0"/>
                </h2>
                <ul>
                    <li t-foreach="column.cards" t-as="card" t-key="card_index" class="card">
                        <span class="label" t-esc="card.node.label"/>
                        <button t-if="card.route" type="button" class="launch" t-att-aria-label="card.name"
                            t-att-title="card.name" t-on-click="() => props.launch(card.route)" t-esc="'▶'"/>
                        <span t-if="props.counts[card.node.path]" class="count" t-esc="props.counts[card.node.path]"/>
                    </li>
                </ul>
            </section>
        </div>
        <p t-else="" class="empty" t-esc="env.t('No command found.')"/>`;

    // Les colonnes, chaque carte avec son plan de route (`route`, null si
    // elle ne se lance pas) et le nom de son bouton (`name`).
    get shown() {
        if (!this.props.tree) {
            return [];
        }
        const {counts, query, sort} = this.props;
        const launch = this.env.t("Launch");
        return kanbanColumns(this.props.tree, counts, query, sort, this.env.lang).map((column) => ({
            ...column,
            cards: column.cards.map((card) => ({
                ...card,
                route: launchRoute(card.nodes),
                name: `${launch} ${card.path}`,
            })),
        }));
    }
}
