const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
    MAX_HEALTH_BYTES,
    HealthWatcher,
    parseHealthBytes,
    readHealthFile,
} = require('../health-contract');

const NOW = new Date('2026-07-20T12:00:00Z');

function envelope(keys = {}, generatedAt = '2026-07-20T12:00:00Z') {
    return Buffer.from(JSON.stringify({ schema_version: 1, generated_at: generatedAt, keys }));
}

test('parses a strict v1 document including a valid empty snapshot', () => {
    const result = parseHealthBytes(envelope({ STRIPE_KEY: {
        status: 'warning', days_old: 67, provider: 'Stripe',
    } }), { now: NOW });
    assert.equal(result.state, 'available');
    assert.equal(result.schemaVersion, 1);
    assert.deepEqual(result.keys.STRIPE_KEY, {
        status: 'warning', days_old: 67, provider: 'Stripe',
    });
    const empty = parseHealthBytes(envelope(), { now: NOW }).keys;
    assert.equal(Object.getPrototypeOf(empty), null);
    assert.deepEqual(Object.keys(empty), []);
});

test('rejects malformed, mixed, unsupported, and oversized documents', () => {
    for (const raw of [
        Buffer.from('{'),
        Buffer.from('{"schema_version":1,"schema_version":1,"generated_at":"2026-07-20T12:00:00Z","keys":{}}'),
        Buffer.from(JSON.stringify({ schema_version: 1, generated_at: '2026-07-20T12:00:00Z', keys: {}, OLD_KEY: {} })),
        Buffer.from(JSON.stringify({ schema_version: 2, generated_at: '2026-07-20T12:00:00Z', keys: {} })),
        Buffer.alloc(MAX_HEALTH_BYTES + 1),
    ]) {
        assert.equal(parseHealthBytes(raw, { now: NOW }).state, 'unavailable');
    }
});

test('normalizes legacy data using mtime freshness and unknown statuses', () => {
    const raw = Buffer.from(JSON.stringify({ LEGACY_KEY: {
        status: 'surprise', days_old: 4, provider: 'Legacy', created: 'ignored',
    } }));
    const result = parseHealthBytes(raw, {
        now: NOW,
        legacyGeneratedAt: new Date('2026-07-20T11:00:00Z'),
    });
    assert.equal(result.state, 'available');
    assert.equal(result.schemaVersion, 0);
    assert.deepEqual(result.keys.LEGACY_KEY, {
        status: 'unknown', days_old: 4, provider: 'Legacy',
    });
});

test('normalizes legacy optional fields and omits ineligible names safely', () => {
    const raw = Buffer.from('{"LEGACY_MISSING":{"status":"healthy"},"LEGACY_INVALID":{"status":"warning","days_old":-1,"provider":"\\ninvalid"},"NOT-AN-ENV-NAME":{"status":"healthy","days_old":1,"provider":"Ignored"},"__proto__":{"status":"critical","days_old":5,"provider":"Prototype Safe"}}');
    const result = parseHealthBytes(raw, {
        now: NOW,
        legacyGeneratedAt: new Date('2026-07-20T11:00:00Z'),
    });
    assert.equal(result.state, 'available');
    assert.deepEqual(result.keys.LEGACY_MISSING, {
        status: 'healthy', days_old: null, provider: null,
    });
    assert.deepEqual(result.keys.LEGACY_INVALID, {
        status: 'warning', days_old: null, provider: null,
    });
    assert.equal(Object.hasOwn(result.keys, 'NOT-AN-ENV-NAME'), false);
    assert.equal(Object.getPrototypeOf(result.keys), null);
    assert.equal(Object.hasOwn(result.keys, '__proto__'), true);
    assert.deepEqual(result.keys.__proto__, {
        status: 'critical', days_old: 5, provider: 'Prototype Safe',
    });
});

test('rejects every mixed legacy and envelope root shape', () => {
    for (const reservedField of ['schema_version', 'generated_at', 'keys']) {
        const result = parseHealthBytes(Buffer.from(JSON.stringify({
            LEGACY_KEY: { status: 'healthy', days_old: 0, provider: null },
            [reservedField]: reservedField === 'keys' ? {} : 'reserved',
        })), {
            now: NOW,
            legacyGeneratedAt: new Date('2026-07-20T11:00:00Z'),
        });
        assert.equal(result.state, 'unavailable', reservedField);
    }
});

test('rejects stale and future v1 snapshots', () => {
    assert.equal(parseHealthBytes(envelope({}, '2026-07-19T09:59:59Z'), { now: NOW }).reason, 'health_stale');
    assert.equal(parseHealthBytes(envelope({}, '2026-07-20T12:05:01Z'), { now: NOW }).reason, 'health_clock_invalid');
});

test('reads at most one MiB plus one byte and clears missing files', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pushkey-health-'));
    const healthFile = path.join(dir, 'health.json');
    try {
        assert.equal(readHealthFile(healthFile, { now: NOW }).reason, 'health_missing');
        fs.writeFileSync(healthFile, envelope());
        assert.equal(readHealthFile(healthFile, { now: NOW }).state, 'available');
        fs.writeFileSync(healthFile, Buffer.alloc(MAX_HEALTH_BYTES + 1));
        assert.equal(readHealthFile(healthFile, { now: NOW }).reason, 'health_too_large');
    } finally {
        fs.rmSync(dir, { recursive: true, force: true });
    }
});

test('watcher debounces atomic replacement reads and reattaches after directory creation', () => {
    const events = [];
    const timers = new Map();
    let nextTimer = 0;
    let watcherCallback;
    let watchCalls = 0;
    const fakeFs = {
        watch(_dir, callback) {
            watchCalls += 1;
            if (watchCalls === 1) throw new Error('directory missing');
            watcherCallback = callback;
            return { close() {}, on() {} };
        },
    };
    const schedule = callback => { const id = ++nextTimer; timers.set(id, callback); return id; };
    const runNextTimer = () => {
        const [id, callback] = timers.entries().next().value;
        timers.delete(id);
        callback();
    };
    const watcher = new HealthWatcher({
        healthFile: path.join('missing', 'health.json'),
        fsModule: fakeFs,
        read: () => ({ state: 'available', keys: {} }),
        onUpdate: result => events.push(result.state),
        setTimeoutFn: schedule,
        clearTimeoutFn: id => timers.delete(id),
    });
    watcher.start();
    assert.equal(events[0], 'available');
    runNextTimer();
    assert.equal(watchCalls, 2);
    watcherCallback('rename', 'health.json');
    watcherCallback('change', 'health.json');
    assert.equal(timers.size, 1);
    runNextTimer();
    assert.deepEqual(events, ['available', 'available']);
    watcher.dispose();
});

test('watcher retries a transient atomic replacement read before clearing state', () => {
    const results = [
        { state: 'unavailable', reason: 'health_missing' },
        { state: 'available', keys: { LIVE_KEY: { status: 'healthy', days_old: 0, provider: null } } },
    ];
    const timers = new Map();
    let nextTimer = 0;
    const watcher = new HealthWatcher({
        healthFile: 'health.json',
        read: () => results.shift(),
        onUpdate: result => assert.equal(result.state, 'available'),
        fsModule: { watch: () => ({ close() {}, on() {} }) },
        setTimeoutFn: callback => { const id = ++nextTimer; timers.set(id, callback); return id; },
        clearTimeoutFn: id => timers.delete(id),
    });
    watcher.start();
    const [id, callback] = timers.entries().next().value;
    timers.delete(id);
    callback();
    watcher.dispose();
});

test('watcher closes and reattaches after a live watcher error', () => {
    const timers = new Map();
    let nextTimer = 0;
    let watchCalls = 0;
    const watchers = [];
    const fakeFs = {
        watch() {
            const handlers = new Map();
            const watcher = {
                closed: false,
                close() { this.closed = true; },
                on(event, handler) { handlers.set(event, handler); },
                emit(event, error) { handlers.get(event)(error); },
            };
            watchers.push(watcher);
            watchCalls += 1;
            return watcher;
        },
    };
    const schedule = callback => { const id = ++nextTimer; timers.set(id, callback); return id; };
    const watcher = new HealthWatcher({
        healthFile: path.join('pushkey', 'health.json'),
        fsModule: fakeFs,
        read: () => ({ state: 'available', keys: {} }),
        onUpdate() {},
        setTimeoutFn: schedule,
        clearTimeoutFn: id => timers.delete(id),
    });
    watcher.start();
    watchers[0].emit('error', new Error('directory removed'));
    assert.equal(watchers[0].closed, true);
    assert.equal(timers.size, 1);
    const [id, callback] = timers.entries().next().value;
    timers.delete(id);
    callback();
    assert.equal(watchCalls, 2);
    watcher.dispose();
    assert.equal(watchers[1].closed, true);
    assert.equal(timers.size, 0);
});
