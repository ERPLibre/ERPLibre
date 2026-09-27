// Vue Historique : les tâches closes des sessions web (/api/tasks), les
// plus récentes d'abord, puis le journal d'une tâche, page par page, en
// lecture seule. Ce qui vient d'un journal s'affiche en texte (t-esc),
// jamais comme du HTML. Purger retire toutes les tâches closes, après
// confirmation ; une tâche encore ouverte reste.
import {Component, onMounted, useState, xml} from "@odoo/owl";
import {getJson, postJson} from "./api.js";
import {duration, recordText, stateLabel, taskCommands, taskRc, taskTitle} from "./history.js";

// Tâches par page de la liste, enregistrements par page de journal.
const TASKS = 50;
const LINES = 500;

export class HistoryView extends Component {
    static template = xml`
        <section class="history">
            <nav class="toolbar" t-att-aria-label="env.t('History')">
                <button t-if="state.task" type="button" t-on-click="() => this.back()" t-esc="env.t('Back')"/>
                <button type="button" t-on-click="() => this.purge()" t-esc="env.t('Purge')"/>
                <span t-if="state.notice" class="summary" t-esc="state.notice"/>
            </nav>
            <p t-if="state.failed" class="error" t-esc="env.t('unavailable')"/>
            <t t-elif="state.task">
                <h2 class="task-title" t-esc="title(state.task)"/>
                <ol class="log">
                    <li t-foreach="state.lines" t-as="record" t-key="record.n" t-att-class="record.s">
                        <span class="n" t-esc="record.n"/>
                        <span t-esc="text(record)"/>
                    </li>
                </ol>
                <button t-if="!state.eof" type="button" t-on-click="() => this.more()" t-esc="env.t('More')"/>
            </t>
            <t t-elif="state.tasks.length">
                <table class="tasks">
                    <thead>
                        <tr>
                            <th t-esc="env.t('Date')"/>
                            <th t-esc="env.t('Task')"/>
                            <th t-esc="env.t('Commands')"/>
                            <th t-esc="env.t('Exit code')"/>
                            <th t-esc="env.t('Duration')"/>
                            <th t-esc="env.t('State')"/>
                        </tr>
                    </thead>
                    <tbody>
                        <tr t-foreach="state.tasks" t-as="task" t-key="task.id">
                            <td t-esc="date(task)"/>
                            <td>
                                <button type="button" class="link" t-on-click="() => this.open(task)"
                                    t-esc="title(task)"/>
                            </td>
                            <td class="cmd" t-esc="commands(task)"/>
                            <td t-esc="rc(task)"/>
                            <td t-esc="length(task)"/>
                            <td t-esc="stateOf(task)"/>
                        </tr>
                    </tbody>
                </table>
                <button t-if="state.more" type="button" t-on-click="() => this.load()" t-esc="env.t('More')"/>
            </t>
            <p t-else="" class="empty" t-esc="env.t('No task recorded yet.')"/>
        </section>`;

    setup() {
        this.state = useState({
            tasks: [],
            more: false,
            task: null,
            lines: [],
            next: 1,
            eof: true,
            failed: false,
            notice: "",
        });
        onMounted(() => this.load(true));
    }

    title(task) {
        return taskTitle(task);
    }

    commands(task) {
        return taskCommands(task);
    }

    rc(task) {
        return taskRc(task);
    }

    length(task) {
        return duration(task.end - task.start);
    }

    stateOf(task) {
        return stateLabel(task.state, this.env.t);
    }

    date(task) {
        return new Date(task.start * 1000).toLocaleString(this.env.lang);
    }

    text(record) {
        return recordText(record, this.env.t);
    }

    // Page suivante de la liste ; `fresh` la reprend depuis la plus récente.
    // Une page qui ne suit plus la dernière tâche listée (un double clic, une
    // purge entre-temps) est ignorée.
    async load(fresh = false) {
        const query = new URLSearchParams({limit: TASKS});
        const last = fresh ? undefined : this.state.tasks.at(-1)?.id;
        if (last) {
            query.set("before", last);
        }
        try {
            const {tasks, more} = await getJson(`/api/tasks?${query}`);
            if (!fresh && this.state.tasks.at(-1)?.id !== last) {
                return;
            }
            this.state.tasks = fresh ? tasks : [...this.state.tasks, ...tasks];
            Object.assign(this.state, {more, failed: false});
        } catch {
            this.state.failed = true;
        }
    }

    async open(task) {
        Object.assign(this.state, {task, lines: [], next: 1, eof: false});
        await this.more();
    }

    // Page suivante du journal ouvert ; ignorée si la vue a changé de tâche
    // ou a déjà reçu cette page (un double clic).
    async more() {
        const {task, next} = this.state;
        const query = new URLSearchParams({from: next, limit: LINES});
        try {
            const page = await getJson(`/api/tasks/${encodeURIComponent(task.id)}?${query}`);
            if (this.state.task?.id === task.id && this.state.next === next) {
                this.state.lines.push(...page.lines);
                Object.assign(this.state, {next: page.next, eof: page.eof});
            }
        } catch {
            this.state.failed = true;
        }
    }

    back() {
        Object.assign(this.state, {task: null, lines: [], failed: false});
    }

    async purge() {
        if (!window.confirm(this.env.t("Purge the whole task history? A task still running is kept."))) {
            return;
        }
        try {
            const {removed} = await postJson("/api/tasks/purge", {});
            this.back();
            this.state.notice = `${this.env.t("Tasks removed:")} ${removed}`;
            await this.load(true);
        } catch {
            this.state.failed = true;
        }
    }
}
