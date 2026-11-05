// Page de télémétrie : une barre d'outils (vues, recherche, tri) au-dessus de
// la vue choisie. La vue et le tri vivent dans le fragment de l'URL, qu'un
// rechargement retrouve ; la recherche n'y entre pas. Une vue qui n'offre
// aucun tri n'offre pas de recherche non plus. La vue Sessions, une fois
// ouverte, reste montée : cachée, sa session continue. Lancer un nœud de
// l'Arbre, de la Liste ou du Kanban ouvre la vue Sessions, qui le rejoue
// (`order`). La vue Historique relit les journaux de tâches. Les libellés
// viennent de `env.t`, la table de traduction de la page.
//
// Tant qu'une vue de l'arbre ou Sessions se voit, la page relit
// /api/telemetry toutes les PERIOD ms, sans que cela compte comme activité
// du hub. L'arbre n'y est remplacé que si le code a changé et que le nouvel
// arbre se lit : un ▶ ne bouge pas sous le pointeur au gré des compteurs,
// qui ne se relisent qu'au changement de vue. Quand l'empreinte du code
// (`code`) n'est plus celle que tourne la session courante, que la vue
// Sessions tient du hub (`runs`), une bannière le dit ; son bouton ouvre
// une session neuve. Une empreinte de session que la page n'a pas encore
// lue la fait relire d'abord : la bannière ne juge que sur la plus récente.
// Dès qu'une requête rend 403, la connexion a expiré : une bannière dit de
// rouvrir l'interface depuis TODO, la page reste telle qu'elle est. Le pied
// de page offre la source (AGPL §13) : le bouton lit /api/source à chaque
// ouverture et montre le dépôt, le commit, la branche, l'état des fichiers
// suivis et les licences des bibliothèques vendorées.
import {Component, onMounted, onWillUnmount, useState, xml} from "@odoo/owl";
import {getJson, onForbidden} from "./api.js";
import {HistoryView} from "./history_view.js";
import {KanbanView} from "./kanban_view.js";
import {ListView} from "./list_view.js";
import {
    Rereads,
    SORTS,
    VIEWS,
    codeChanged,
    effectiveSort,
    pollsCode,
    readFragment,
    rereadsFor,
    writeFragment,
} from "./model.js";
import {SessionsView} from "./sessions_view.js";
import {noticeLine, sourceRows} from "./source.js";
import {SystemView} from "./system_view.js";
import {TreeView} from "./tree_view.js";

const VIEW_LABELS = {
    tree: "Tree",
    list: "List",
    kanban: "Kanban",
    system: "System",
    sessions: "Sessions",
    history: "History",
};
const SORT_LABELS = {code: "Code order", usage: "Most used", name: "Name"};
const PERIOD = 10000;

export class TelemetryPage extends Component {
    static components = {HistoryView, KanbanView, ListView, SessionsView, SystemView, TreeView};
    static template = xml`
        <header class="bar">
            <h1 t-esc="env.t('TODO navigation telemetry')"/>
            <span class="root" t-esc="props.root"/>
        </header>
        <div t-if="state.expired" class="banner" role="alert">
            <span t-esc="env.t('Connection expired: reopen the interface from TODO › Navigation telemetry.')"/>
        </div>
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
        <div t-if="stale" class="banner" role="status">
            <span t-esc="staleText"/>
            <button type="button" t-on-click="reopen" t-esc="env.t('Reopen a session')"/>
        </div>
        <p t-if="state.view !== 'sessions' and state.view !== 'history'" class="summary" t-esc="summary"/>
        <TreeView t-if="state.view === 'tree'" t-key="sort + '|' + state.query" tree="tree" counts="counts"
            query="state.query" sort="sort" launch.bind="launch"/>
        <ListView t-elif="state.view === 'list'" tree="tree" counts="counts" query="state.query" sort="sort"
            launch.bind="launch"/>
        <KanbanView t-elif="state.view === 'kanban'" tree="tree" counts="counts" query="state.query" sort="sort"
            launch.bind="launch"/>
        <SystemView t-elif="state.view === 'system'"/>
        <HistoryView t-elif="state.view === 'history'"/>
        <SessionsView t-if="state.terminal" visible="state.view === 'sessions'" openView.bind="openView"
            order="state.order" runs.bind="sessionRuns"/>
        <footer class="source">
            <button type="button" t-att-aria-expanded="state.source ? 'true' : 'false'" t-on-click="toggleSource"
                t-esc="env.t('Source (AGPL-3.0)')"/>
            <dl t-if="state.source">
                <t t-foreach="sourceRows" t-as="row" t-key="row_index">
                    <dt t-esc="row[0]"/>
                    <dd t-esc="row[1]"/>
                </t>
                <dt t-esc="env.t('Vendored libraries')"/>
                <dd t-foreach="notices" t-as="notice" t-key="notice.href">
                    <a t-att-href="notice.href" t-esc="notice.text"/>
                </dd>
            </dl>
        </footer>`;

    setup() {
        this.views = VIEWS;
        this.viewLabels = VIEW_LABELS;
        this.sortLabels = SORT_LABELS;
        const fragment = readFragment(window.location.hash);
        const {telemetry} = this.props;
        // `order` : le dernier ordre donné à la vue Sessions ; `telemetry` :
        // l'arbre et les compteurs montrés ; `latest` : la dernière empreinte
        // lue ; `runs` : celle que tourne la session courante, ou null.
        this.state = useState({...fragment, query: "", terminal: fragment.view === "sessions", order: null});
        Object.assign(this.state, {telemetry, latest: telemetry.code, runs: null, expired: false, source: null});
        this.told = 0; // le rang du dernier appel de sessionRuns
        this.rereads = new Rereads(); // l'ordre des relectures de /api/telemetry
        onForbidden(() => (this.state.expired = true));
        onMounted(() => {
            this.timer = setInterval(() => {
                if (pollsCode(this.state.view, document.visibilityState)) {
                    this.refresh();
                }
            }, PERIOD);
        });
        onWillUnmount(() => {
            clearInterval(this.timer);
            onForbidden(null);
        });
    }

    get tree() {
        return this.state.telemetry.tree;
    }

    get counts() {
        return this.state.telemetry.counts;
    }

    get stale() {
        return codeChanged(this.state.runs, this.state.latest);
    }

    get staleText() {
        return this.env.t("TODO's code changed: open sessions still run the old one. Reopen a session to use it.");
    }

    get sorts() {
        return SORTS[this.state.view] || [];
    }

    get sourceRows() {
        return sourceRows(this.state.source, this.env.t);
    }

    get notices() {
        return this.state.source.notices.map(noticeLine);
    }

    // Ouvre l'offre de source, relue du hub, ou la ferme ; un hub qui ne
    // répond pas la laisse fermée.
    async toggleSource() {
        if (this.state.source) {
            this.state.source = null;
            return;
        }
        try {
            this.state.source = await getJson("/api/source");
        } catch {
            this.state.source = null;
        }
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
        this.state.terminal ||= view === "sessions";
        this.remember();
        this.refresh(true);
    }

    // Lance un nœud : la vue Sessions rejoue son plan de route `route`, le
    // menu principal ayant pour fil d'Ariane la clé de la racine. Un ordre
    // neuf à chaque appel, même pour le même nœud.
    launch(route) {
        this.state.order = {route, root: this.tree.key};
        this.show("sessions");
    }

    // Le bouton de la bannière : la vue Sessions ferme la session courante
    // si elle attend à un menu et en ouvre une neuve.
    reopen() {
        this.state.order = {reopen: true};
        this.show("sessions");
    }

    // L'empreinte du code que tourne la session courante de la vue
    // Sessions, null quand elle n'en a pas. Une empreinte qui n'est pas la
    // dernière lue (`rereadsFor`) ne compte qu'après une relecture de fond,
    // et seulement si aucun appel plus récent ne l'a remplacée entre-temps.
    async sessionRuns(code) {
        const told = ++this.told;
        if (rereadsFor(code, this.state.latest)) {
            await this.refresh();
        }
        if (told === this.told) {
            this.state.runs = code;
        }
    }

    // Relit /api/telemetry : son empreinte va à la bannière ; l'arbre et les
    // compteurs ne sont remplacés qu'avec `all`, au changement de vue, ou
    // quand le code a changé, et jamais par un arbre illisible (null).
    // Seule la relecture de fond (`poll=1`) ne compte pas comme activité. Un
    // hub qui ne répond pas laisse tout tel quel jusqu'à la suivante. La
    // réponse d'une relecture qu'une plus récente a devancée ne donne pas
    // son empreinte, plus ancienne peut-être ; complète, elle remplace
    // encore l'arbre et les compteurs quand son empreinte est la dernière
    // lue (`Rereads`).
    async refresh(all = false) {
        const rank = this.rereads.ask();
        try {
            const telemetry = await getJson(`/api/telemetry?lang=${this.env.lang}${all ? "" : "&poll=1"}`);
            const {stamp, tree} = this.rereads.reply(rank, {
                all,
                code: telemetry.code,
                latest: this.state.latest,
                shown: this.state.telemetry.code,
                readable: Boolean(telemetry.tree),
            });
            if (stamp) {
                this.state.latest = telemetry.code;
            }
            if (tree) {
                this.state.telemetry = telemetry;
            }
        } catch {
            // La relecture suivante réessaie.
        }
    }

    // Vue que le TODO d'une session demande à la page d'ouvrir.
    openView(view) {
        if (view === "telemetry") {
            this.show("tree");
        }
    }

    sortBy(sort) {
        this.state.sort = sort;
        this.remember();
    }
}
