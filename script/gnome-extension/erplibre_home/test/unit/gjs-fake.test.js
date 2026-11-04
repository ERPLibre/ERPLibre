import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';

const FAKE = new URL('./gjs-fake.js', import.meta.url).href;

test('the fake removes its temporary directories on reset and at exit',
    () => {
        const child = spawnSync(process.execPath, [
            '--input-type=module', '-e',
            `import {fake} from ${JSON.stringify(FAKE)};
            const first = fake.root;
            fake.reset();
            console.log(JSON.stringify({first, last: fake.root}));`,
        ], {encoding: 'utf8'});
        assert.equal(child.status, 0, child.stderr);
        const {first, last} = JSON.parse(child.stdout);
        assert.match(first, /gjs-fake-/);
        assert.notEqual(first, last);
        assert.equal(existsSync(first), false);
        assert.equal(existsSync(last), false);
    });
