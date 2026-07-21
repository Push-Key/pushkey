'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
    MAX_HEALTH_BYTES,
    countByStatus,
    parseHealthResponse,
} = require('../health-contract');

const NOW = new Date('2026-07-20T12:00:00Z');

function envelope(keys = {}, generatedAt = '2026-07-20T12:00:00Z') {
    return JSON.stringify({ schema_version: 1, generated_at: generatedAt, keys });
}

test('accepts strict v1 documents and calculates aggregate counts', () => {
    const result = parseHealthResponse(envelope({
        HEALTHY_KEY: { status: 'healthy', days_old: 2, provider: 'OpenAI' },
        WARNING_KEY: { status: 'warning', days_old: 70, provider: null },
        CRITICAL_KEY: { status: 'critical', days_old: 100, provider: 'Stripe' },
        UNKNOWN_KEY: { status: 'unknown', days_old: null, provider: null },
    }), { now: NOW });

    assert.equal(result.state, 'available');
    assert.equal(result.schemaVersion, 1);
    assert.deepEqual(countByStatus(result.keys), {
        healthy: 1, warning: 1, critical: 1, unknown: 1,
    });
});

test('normalizes legacy records and rejects mixed legacy/envelope shapes', () => {
    const legacy = parseHealthResponse(JSON.stringify({
        LEGACY_KEY: { status: 'surprise', days_old: -1, provider: '\ninvalid', created: 'ignored' },
        'NOT-AN-ENV-NAME': { status: 'healthy', days_old: 1, provider: 'Ignored' },
    }), { now: NOW, legacyGeneratedAt: new Date('2026-07-20T11:00:00Z') });
    assert.equal(legacy.state, 'available');
    assert.deepEqual(legacy.keys.LEGACY_KEY, {
        status: 'unknown', days_old: null, provider: null,
    });
    assert.equal(Object.hasOwn(legacy.keys, 'NOT-AN-ENV-NAME'), false);

    for (const reservedField of ['schema_version', 'generated_at', 'keys']) {
        const mixed = { LEGACY_KEY: { status: 'healthy', days_old: 1, provider: null } };
        mixed[reservedField] = reservedField === 'keys' ? {} : 'reserved';
        assert.equal(parseHealthResponse(JSON.stringify(mixed), {
            now: NOW,
            legacyGeneratedAt: new Date('2026-07-20T11:00:00Z'),
        }).state, 'unavailable');
    }
});

test('rejects expired and future-skewed snapshots', () => {
    assert.equal(parseHealthResponse(envelope({}, '2026-07-19T09:59:59Z'), { now: NOW }).reason, 'health_stale');
    assert.equal(parseHealthResponse(envelope({}, '2026-07-20T12:05:01Z'), { now: NOW }).reason, 'health_clock_invalid');
});

test('treats malformed, oversized, unsupported, and unknown-status v1 input as unavailable', () => {
    for (const raw of [
        '{',
        'x'.repeat(MAX_HEALTH_BYTES + 1),
        JSON.stringify({ schema_version: 2, generated_at: '2026-07-20T12:00:00Z', keys: {} }),
        envelope({ BAD_STATUS: { status: 'surprise', days_old: 1, provider: null } }),
    ]) {
        assert.equal(parseHealthResponse(raw, { now: NOW }).state, 'unavailable');
    }
});

test('keeps markup-like key names unavailable to the trusted UI contract', () => {
    const result = parseHealthResponse(envelope({
        '<img src=x onerror=alert(1)>': { status: 'warning', days_old: 7, provider: null },
    }), { now: NOW });
    assert.equal(result.state, 'unavailable');
});

test('returns unavailable for HTTP failures and supports valid empty snapshots', () => {
    assert.equal(parseHealthResponse(null, { now: NOW }).state, 'unavailable');
    const empty = parseHealthResponse(envelope(), { now: NOW });
    assert.equal(empty.state, 'available');
    assert.deepEqual(Object.keys(empty.keys), []);
});
