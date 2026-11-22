'use strict';

(function initHealthContract(globalScope) {
    const MAX_HEALTH_BYTES = 1024 * 1024;
    const MAX_AGE_MS = 26 * 60 * 60 * 1000;
    const MAX_FUTURE_MS = 5 * 60 * 1000;
    const KEY_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/;
    const PROVIDER = /^[\x20-\x7e]{1,64}$/;
    const STATUSES = new Set(['healthy', 'warning', 'critical', 'unknown']);
    const ROOT_FIELDS = new Set(['schema_version', 'generated_at', 'keys']);
    const RECORD_FIELDS = new Set(['status', 'days_old', 'provider']);

    function unavailable(reason) { return { state: 'unavailable', reason }; }

    function validDate(value) {
        if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value)) return null;
        const date = new Date(value);
        return Number.isFinite(date.getTime()) && date.toISOString().replace('.000Z', 'Z') === value ? date : null;
    }

    function currentDate(value, now) {
        if (!(value instanceof Date) || !Number.isFinite(value.getTime())) return unavailable('health_clock_invalid');
        const delta = value.getTime() - now.getTime();
        if (delta < -MAX_AGE_MS) return unavailable('health_stale');
        if (delta > MAX_FUTURE_MS) return unavailable('health_clock_invalid');
        return null;
    }

    function assertNoDuplicateJsonKeys(text) {
        let index = 0;
        const skip = () => { while (/\s/.test(text[index])) index += 1; };
        const string = () => {
            const start = index;
            if (text[index] !== '"') throw new Error('invalid JSON string');
            index += 1;
            while (index < text.length) {
                if (text[index] === '\\') { index += 2; continue; }
                if (text[index] === '"') { index += 1; return JSON.parse(text.slice(start, index)); }
                index += 1;
            }
            throw new Error('unterminated JSON string');
        };
        const value = () => {
            skip();
            if (text[index] === '{') {
                index += 1; skip();
                const seen = new Set();
                if (text[index] === '}') { index += 1; return; }
                while (true) {
                    skip();
                    const key = string();
                    if (seen.has(key)) throw new Error('duplicate JSON key');
                    seen.add(key); skip();
                    if (text[index] !== ':') throw new Error('invalid JSON object');
                    index += 1; value(); skip();
                    if (text[index] === '}') { index += 1; return; }
                    if (text[index] !== ',') throw new Error('invalid JSON object');
                    index += 1;
                }
            }
            if (text[index] === '[') {
                index += 1; skip();
                if (text[index] === ']') { index += 1; return; }
                while (true) {
                    value(); skip();
                    if (text[index] === ']') { index += 1; return; }
                    if (text[index] !== ',') throw new Error('invalid JSON array');
                    index += 1;
                }
            }
            if (text[index] === '"') { string(); return; }
            const start = index;
            while (index < text.length && !/[\s,}\]]/.test(text[index])) index += 1;
            JSON.parse(text.slice(start, index));
        };
        value(); skip();
        if (index !== text.length) throw new Error('invalid JSON suffix');
    }

    function normalizeRecord(record, strict) {
        if (!record || typeof record !== 'object' || Array.isArray(record)) return null;
        const fields = Object.keys(record);
        if (strict && (fields.length !== 3 || fields.some(field => !RECORD_FIELDS.has(field)))) return null;
        const status = typeof record.status === 'string' && STATUSES.has(record.status)
            ? record.status : (strict ? null : 'unknown');
        const validDays = record.days_old === null ||
            (Number.isInteger(record.days_old) && record.days_old >= 0 && record.days_old <= 365000);
        const validProvider = record.provider === null ||
            (typeof record.provider === 'string' && PROVIDER.test(record.provider));
        if (!status || (strict && (!validDays || !validProvider))) return null;
        return { status, days_old: validDays ? record.days_old : null, provider: validProvider ? record.provider : null };
    }

    function normalizeKeys(keys, strict) {
        if (!keys || typeof keys !== 'object' || Array.isArray(keys) || Object.keys(keys).length > 10000) return null;
        const normalized = Object.create(null);
        for (const [name, record] of Object.entries(keys)) {
            if (!KEY_NAME.test(name)) {
                if (strict) return null;
                continue;
            }
            const item = normalizeRecord(record, strict);
            if (!item) return null;
            Object.defineProperty(normalized, name, { value: item, enumerable: true, configurable: true, writable: true });
        }
        return normalized;
    }

    function parseHealthResponse(raw, { now = new Date(), legacyGeneratedAt = now } = {}) {
        if (typeof raw !== 'string') return unavailable('health_unavailable');
        if (new TextEncoder().encode(raw).length > MAX_HEALTH_BYTES) return unavailable('health_too_large');
        let document;
        try {
            assertNoDuplicateJsonKeys(raw);
            document = JSON.parse(raw);
        } catch (_) { return unavailable('health_malformed_json'); }
        if (!document || typeof document !== 'object' || Array.isArray(document)) return unavailable('health_schema_invalid');
        if ([...ROOT_FIELDS].some(field => Object.prototype.hasOwnProperty.call(document, field))) {
            if (document.schema_version !== 1 || Object.keys(document).length !== 3 || Object.keys(document).some(field => !ROOT_FIELDS.has(field))) return unavailable('health_unsupported_version');
            const generatedAt = validDate(document.generated_at);
            const keys = normalizeKeys(document.keys, true);
            if (!generatedAt || !keys) return unavailable('health_schema_invalid');
            return currentDate(generatedAt, now) || { state: 'available', schemaVersion: 1, keys };
        }
        const keys = normalizeKeys(document, false);
        if (!keys) return unavailable('health_schema_invalid');
        return currentDate(legacyGeneratedAt, now) || { state: 'available', schemaVersion: 0, keys };
    }

    function countByStatus(keys) {
        const counts = { healthy: 0, warning: 0, critical: 0, unknown: 0 };
        for (const record of Object.values(keys || {})) if (record && STATUSES.has(record.status)) counts[record.status] += 1;
        return counts;
    }

    const api = { MAX_HEALTH_BYTES, countByStatus, parseHealthResponse };
    globalScope.PushkeyHealthContract = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof globalThis === 'undefined' ? this : globalThis));
