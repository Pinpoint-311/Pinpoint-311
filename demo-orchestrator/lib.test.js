import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    validateId, sanitizeTownName, composeInvocation, caddyReloadInvocation, generateDemoSubdomains,
} from './lib.js';

const CONFIG = {
    BASE_PORT: 9200, BACKEND_BASE: 9000, FRONTEND_BASE: 9100,
    COMPOSE_FILE: '/srv/demo dir/docker-compose-demo.yml',
    CADDY_CONTAINER: 'caddy-1',
    GOOGLE_CLOUD_PROJECT: 'proj; touch /tmp/pwned',
    GOOGLE_VERTEX_PROJECT: '', GOOGLE_VERTEX_LOCATION: 'us-central1',
};

test('validateId accepts generated ids and rejects everything else', () => {
    assert.ok(validateId('ab12cd34'));
    for (const bad of ['ab', 'ABCD', 'abcd;id', '__proto__', 'abcdefghi', 12345678, undefined]) {
        assert.equal(validateId(bad), false, String(bad));
    }
});

test('composeInvocation builds an argv array; config values stay single arguments', () => {
    const { file, args, env } = composeInvocation(CONFIG, 'ab12cd34', 9201, ['down', '-v']);
    assert.equal(file, 'docker');
    assert.deepEqual(args, ['compose', '-p', 'p311demo_ab12cd34', '-f', '/srv/demo dir/docker-compose-demo.yml', 'down', '-v']);
    assert.equal(env.DEMO_BACKEND_PORT, '9001');
    assert.equal(env.DEMO_FRONTEND_PORT, '9101');
    // Passed through the environment, never through a shell.
    assert.equal(env.GOOGLE_CLOUD_PROJECT, 'proj; touch /tmp/pwned');
});

test('composeInvocation rejects bad ids and ports', () => {
    assert.throws(() => composeInvocation(CONFIG, 'x; rm -rf /', 9201, ['down']), /Invalid instance ID/);
    assert.throws(() => composeInvocation(CONFIG, 'ab12cd34', '9201; id', ['down']), /Invalid port/);
    assert.throws(() => composeInvocation(CONFIG, 'ab12cd34', 80, ['down']), /Invalid port/);
});

test('caddyReloadInvocation keeps the container name as one argument', () => {
    const { args } = caddyReloadInvocation({ CADDY_CONTAINER: 'c $(id)' });
    assert.deepEqual(args, ['exec', 'c $(id)', 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile']);
});

test('sanitizeTownName strips newlines, braces and other Caddyfile syntax', () => {
    assert.equal(sanitizeTownName("  St. Mary's   Township & Co-op "), "St. Mary's Township & Co-op");
    assert.equal(sanitizeTownName('Montréal'), 'Montréal');
    assert.equal(sanitizeTownName('x)\nevil.example {\n respond "hi"\n}'), 'x evil.example respond hi');
    assert.equal(sanitizeTownName({}), '');
    assert.equal(sanitizeTownName('a'.repeat(500)).length, 80);
});

test('generateDemoSubdomains cannot be broken out of by a hostile town name', () => {
    const out = generateDemoSubdomains({
        ab12cd34: { status: 'ready', port: 9201, townName: 'x)\n:80 {\n respond "owned"\n}\n#' },
        zz99zz99: { status: 'failed', port: 9202, townName: 'Gone' },
        '../../x': { status: 'ready', port: 9203, townName: 'bad id' },
    }, 'pinpoint311.org');
    assert.equal(out, [
        '# Demo: ab12cd34 (x 80 respond owned)',
        'demo-ab12cd34.pinpoint311.org {',
        '    reverse_proxy host.docker.internal:9201',
        '}',
        '',
    ].join('\n'));
});
