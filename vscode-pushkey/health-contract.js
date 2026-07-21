'use strict';

const fs = require('fs');
const path = require('path');

const MAX_HEALTH_BYTES = 1024 * 1024;
const MAX_AGE_MS = 26 * 60 * 60 * 1000;
const MAX_FUTURE_MS = 5 * 60 * 1000;
const KEY_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/;
const PROVIDER = /^[\x20-\x7e]{1,64}$/;
const STATUSES = new Set(['healthy', 'warning', 'critical', 'unknown']);
const ROOT_FIELDS = new Set(['schema_version', 'generated_at', 'keys']);
const RECORD_FIELDS = new Set(['status', 'days_old', 'provider']);

function unavailable(reason) {
    return { state: 'unavailable', reason };
}

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
    const whitespace = /\s/;
    const skip = () => { while (whitespace.test(text[index])) index += 1; };
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
            index += 1;
            skip();
            const seen = new Set();
            if (text[index] === '}') { index += 1; return; }
            while (true) {
                skip();
                const key = string();
                if (seen.has(key)) throw new Error('duplicate JSON key');
                seen.add(key);
                skip();
                if (text[index] !== ':') throw new Error('invalid JSON object');
                index += 1;
                value();
                skip();
                if (text[index] === '}') { index += 1; return; }
                if (text[index] !== ',') throw new Error('invalid JSON object');
                index += 1;
            }
        }
        if (text[index] === '[') {
            index += 1;
            skip();
            if (text[index] === ']') { index += 1; return; }
            while (true) {
                value();
                skip();
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
    value();
    skip();
    if (index !== text.length) throw new Error('invalid JSON suffix');
}

function normalizeRecord(record, strict) {
    if (!record || typeof record !== 'object' || Array.isArray(record)) return null;
    if (strict && (Object.keys(record).length !== 3 || Object.keys(record).some(field => !RECORD_FIELDS.has(field)))) return null;
    const status = typeof record.status === 'string' && STATUSES.has(record.status)
        ? record.status
        : (strict ? null : 'unknown');
    const daysOld = record.days_old;
    const validDays = daysOld === null || (Number.isInteger(daysOld) && daysOld >= 0 && daysOld <= 365000);
    const provider = record.provider;
    const validProvider = provider === null || (typeof provider === 'string' && PROVIDER.test(provider));
    if (!status || !validDays || !validProvider) return null;
    return { status, days_old: daysOld, provider };
}

function normalizeKeys(keys, strict) {
    if (!keys || typeof keys !== 'object' || Array.isArray(keys) || Object.keys(keys).length > 10000) return null;
    const normalized = {};
    for (const [name, record] of Object.entries(keys)) {
        if (!KEY_NAME.test(name)) return null;
        const item = normalizeRecord(record, strict);
        if (!item) return null;
        normalized[name] = item;
    }
    return normalized;
}

function parseHealthBytes(raw, { now = new Date(), legacyGeneratedAt = null } = {}) {
    if (!Buffer.isBuffer(raw)) return unavailable('health_schema_invalid');
    if (raw.length > MAX_HEALTH_BYTES) return unavailable('health_too_large');
    let document;
    try {
        const text = raw.toString('utf8');
        assertNoDuplicateJsonKeys(text);
        document = JSON.parse(text);
    } catch (_) { return unavailable('health_malformed_json'); }
    if (!document || typeof document !== 'object' || Array.isArray(document)) return unavailable('health_schema_invalid');
    if (Object.prototype.hasOwnProperty.call(document, 'schema_version')) {
        if (document.schema_version !== 1 || Object.keys(document).length !== 3 || Object.keys(document).some(field => !ROOT_FIELDS.has(field))) {
            return unavailable('health_unsupported_version');
        }
        const generatedAt = validDate(document.generated_at);
        const keys = normalizeKeys(document.keys, true);
        if (!generatedAt || !keys) return unavailable('health_schema_invalid');
        const freshness = currentDate(generatedAt, now);
        return freshness || { state: 'available', schemaVersion: 1, generatedAt, keys };
    }
    const generatedAt = legacyGeneratedAt;
    const keys = normalizeKeys(document, false);
    if (!keys) return unavailable('health_schema_invalid');
    const freshness = currentDate(generatedAt, now);
    return freshness || { state: 'available', schemaVersion: 0, generatedAt, keys };
}

function readHealthFile(healthFile, { now = new Date(), fsModule = fs } = {}) {
    let fd;
    try {
        fd = fsModule.openSync(healthFile, 'r');
        const buffer = Buffer.alloc(MAX_HEALTH_BYTES + 1);
        const bytesRead = fsModule.readSync(fd, buffer, 0, buffer.length, 0);
        const stat = fsModule.fstatSync(fd);
        return parseHealthBytes(buffer.subarray(0, bytesRead), { now, legacyGeneratedAt: stat.mtime });
    } catch (error) {
        return unavailable(error && error.code === 'ENOENT' ? 'health_missing' : 'health_unavailable');
    } finally {
        if (fd !== undefined) try { fsModule.closeSync(fd); } catch (_) {}
    }
}

class HealthWatcher {
    constructor({ healthFile, onUpdate, read = readHealthFile, fsModule = fs, setTimeoutFn = setTimeout, clearTimeoutFn = clearTimeout, debounceMs = 75, retryMs = 100, maxRetries = 3 }) {
        this.healthFile = healthFile;
        this.onUpdate = onUpdate;
        this.read = read;
        this.fs = fsModule;
        this.setTimeout = setTimeoutFn;
        this.clearTimeout = clearTimeoutFn;
        this.debounceMs = debounceMs;
        this.retryMs = retryMs;
        this.maxRetries = maxRetries;
        this.fileWatcher = null;
        this.timer = null;
        this.disposed = false;
    }
    start() { this.refresh(); this.attach(); }
    refresh(attempt = 0) {
        if (this.disposed) return;
        const result = this.read(this.healthFile);
        if (result.state === 'unavailable' &&
            (result.reason === 'health_unavailable' || result.reason === 'health_missing') &&
            attempt < this.maxRetries) {
            this.schedule(() => this.refresh(attempt + 1), this.retryMs);
            return;
        }
        this.onUpdate(result);
    }
    attach() {
        if (this.disposed) return;
        if (this.fileWatcher) this.fileWatcher.close();
        try {
            this.fileWatcher = this.fs.watch(path.dirname(this.healthFile), (_event, filename) => {
                if (filename !== null && filename !== undefined && String(filename) !== path.basename(this.healthFile)) return;
                this.schedule(() => this.refresh(), this.debounceMs);
            });
        } catch (_) {
            this.schedule(() => this.attach(), this.retryMs);
        }
    }
    schedule(callback, delay) {
        if (this.timer !== null) this.clearTimeout(this.timer);
        this.timer = this.setTimeout(() => { this.timer = null; callback(); }, delay);
    }
    dispose() {
        this.disposed = true;
        if (this.timer !== null) this.clearTimeout(this.timer);
        if (this.fileWatcher) this.fileWatcher.close();
    }
}

module.exports = { MAX_HEALTH_BYTES, HealthWatcher, parseHealthBytes, readHealthFile };
