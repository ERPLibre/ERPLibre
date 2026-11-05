// Vue Système : le relevé de /api/system toutes les PERIOD ms, tant que la
// vue est montée et la page visible. Cachée, la page n'interroge plus le
// hub ; revenue, elle relève aussitôt puis reprend le rythme.
import {Component, onMounted, onWillUnmount, useState, xml} from "@odoo/owl";
import {getJson} from "./api.js";
import {systemRows} from "./metrics.js";

const PERIOD = 2000;

export class SystemView extends Component {
    static template = xml`
        <p t-if="state.failed" class="error" t-esc="env.t('unavailable')"/>
        <dl t-elif="state.metrics" class="system">
            <t t-foreach="rows" t-as="row" t-key="row_index">
                <dt t-esc="row[0]"/>
                <dd>
                    <span t-esc="row[1]"/>
                    <meter t-if="row[2] !== null" min="0" max="1" t-att-value="row[2]"/>
                </dd>
            </t>
        </dl>
        <p t-else="" class="summary">…</p>`;

    setup() {
        this.state = useState({metrics: null, temp: null, failed: false});
        this.timer = null;
        this.busy = false;
        this.alive = true;
        const onVisibility = () => (document.visibilityState === "visible" ? this.start() : this.stop());
        onMounted(() => {
            document.addEventListener("visibilitychange", onVisibility);
            this.start();
        });
        onWillUnmount(() => {
            this.alive = false;
            document.removeEventListener("visibilitychange", onVisibility);
            this.stop();
        });
    }

    get rows() {
        return systemRows(this.state.metrics, this.state.temp, this.env.t, this.env.lang);
    }

    start() {
        if (this.timer === null && document.visibilityState === "visible") {
            this.timer = setInterval(() => this.poll(), PERIOD);
            this.poll();
        }
    }

    stop() {
        clearInterval(this.timer);
        this.timer = null;
    }

    async poll() {
        // Un relevé lent ne s'empile pas sous le suivant.
        if (this.busy) {
            return;
        }
        this.busy = true;
        try {
            const {metrics, full} = await getJson("/api/system");
            if (this.alive) {
                if (full) {
                    this.state.temp = metrics.temp;
                }
                Object.assign(this.state, {metrics, failed: false});
            }
        } catch {
            if (this.alive) {
                this.state.failed = true;
            }
        } finally {
            this.busy = false;
        }
    }
}
