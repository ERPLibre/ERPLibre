export class Debouncer {
    constructor({delayMs, scheduler = setTimeout, canceller = clearTimeout}) {
        this._delay = delayMs;
        this._sched = scheduler;
        this._cancel = canceller;
        this._handle = null;
    }
    bump(fn) {
        if (this._handle !== null) this._cancel(this._handle);
        this._handle = this._sched(() => { this._handle = null; fn(); },
            this._delay);
    }
    flush() {
        if (this._handle !== null) this._cancel(this._handle);
        this._handle = null;
    }
}

/**
 * GJS-only — git pull --rebase / commit / push helpers.
 */
export async function gitPull(repoPath) {
    const {default: Gio} = await import('gi://Gio');
    return new Promise(resolve => {
        try {
            const proc = Gio.Subprocess.new(
                ['git', '-C', repoPath, 'pull', '--rebase',
                 '--strategy-option=theirs'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    p.communicate_utf8_finish(res);
                    resolve(p.get_successful());
                } catch (_e) { resolve(false); }
            });
        } catch (_e) { resolve(false); }
    });
}

export async function gitCommitPush(repoPath, hostname) {
    const {default: Gio} = await import('gi://Gio');
    const ts = new Date().toISOString();
    const message = `auto sync ${hostname} ${ts}`;
    return new Promise(resolve => {
        try {
            const proc = Gio.Subprocess.new(
                ['bash', '-c',
                 `cd "${repoPath}" && git add -A && ` +
                 `git commit -m "${message}" --allow-empty && ` +
                 `if git remote get-url origin >/dev/null 2>&1; then ` +
                 `git push; fi`],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            proc.communicate_utf8_async(null, null, (p, res) => {
                try {
                    p.communicate_utf8_finish(res);
                    resolve(p.get_successful());
                } catch (_e) { resolve(false); }
            });
        } catch (_e) { resolve(false); }
    });
}
