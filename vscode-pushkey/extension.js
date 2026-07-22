const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const os = require('os');

const HEALTH_FILE = path.join(os.homedir(), '.pushkey', 'health.json');

// Decoration types — one per status
let decorations = {};
let healthData = {};
let fileWatcher = null;
let reattachTimer = null;

function makeDecorationType(iconFile) {
    return vscode.window.createTextEditorDecorationType({
        gutterIconPath: path.join(__dirname, 'icons', iconFile),
        gutterIconSize: '70%',
    });
}

function loadHealth() {
    try {
        if (!fs.existsSync(HEALTH_FILE)) {
            // Missing sidecar should behave like an empty health object.
            healthData = {};
            return;
        }
        const parsed = JSON.parse(fs.readFileSync(HEALTH_FILE, 'utf8'));
        healthData = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (_) {
        healthData = {};
    }
}

function applyDecorations(editor) {
    if (!editor) return;

    const { document } = editor;
    const fname = document.fileName;

    // Only decorate .env files
    const base = path.basename(fname);
    if (!base.startsWith('.env') && base !== '.env') return;

    const byStatus = { healthy: [], warning: [], critical: [] };

    for (let i = 0; i < document.lineCount; i++) {
        const line = document.lineAt(i);
        const text = line.text;

        // Skip comments and blank lines
        if (!text.trim() || text.trim().startsWith('#')) continue;

        // Parse KEY=value
        const match = text.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=/);
        if (!match) continue;

        const keyName = match[1];
        const info = healthData[keyName];
        if (!info) continue;

        const status = info.status || 'healthy';
        if (byStatus[status]) {
            byStatus[status].push({
                range: new vscode.Range(i, 0, i, 0),
                hoverMessage: buildHoverMessage(keyName, info),
            });
        }
    }

    editor.setDecorations(decorations.healthy,  byStatus.healthy);
    editor.setDecorations(decorations.warning,  byStatus.warning);
    editor.setDecorations(decorations.critical, byStatus.critical);
}

function buildHoverMessage(keyName, info) {
    const statusEmoji = { healthy: '🟢', warning: '🟡', critical: '🔴' }[info.status] || '⚪';
    const lines = [
        `**Pushkey** — ${statusEmoji} ${(info.status || 'unknown').toUpperCase()}`,
        '',
        `\`${keyName}\``,
    ];
    if (info.provider)   lines.push(`Provider: ${info.provider}`);
    if (info.days_old != null) lines.push(`Age: **${info.days_old} days**`);
    if (info.created)    lines.push(`Created: ${info.created.slice(0, 10)}`);
    if (info.rotated)    lines.push(`Rotated: ${info.rotated.slice(0, 10)}`);
    if (info.first_used) lines.push(`In use since: ${info.first_used.slice(0, 10)}`);
    if (info.status === 'critical') {
        lines.push('', '⚠️ **Rotation overdue — open Pushkey to rotate**');
    } else if (info.status === 'warning') {
        lines.push('', '⚠️ Rotation recommended soon');
    }

    const md = new vscode.MarkdownString(lines.join('\n'));
    md.isTrusted = true;
    return md;
}

function refreshAll() {
    loadHealth();
    for (const editor of vscode.window.visibleTextEditors) {
        applyDecorations(editor);
    }
}

function clearReattachTimer() {
    if (reattachTimer) {
        clearTimeout(reattachTimer);
        reattachTimer = null;
    }
}

function scheduleWatchReattach(delayMs = 1000) {
    clearReattachTimer();
    reattachTimer = setTimeout(() => {
        reattachTimer = null;
        watchHealthFile();
    }, delayMs);
    if (reattachTimer && typeof reattachTimer.unref === 'function') {
        reattachTimer.unref();
    }
}

function watchHealthFile() {
    clearReattachTimer();
    if (fileWatcher) fileWatcher.close();
    try {
        fileWatcher = fs.watch(path.dirname(HEALTH_FILE), (eventType, filename) => {
            if (filename === 'health.json') refreshAll();
        });
        if (fileWatcher && typeof fileWatcher.on === 'function') {
            fileWatcher.on('error', () => scheduleWatchReattach());
            fileWatcher.on('close', () => scheduleWatchReattach());
        }
    } catch (_) {
        // ~/.pushkey doesn't exist yet — retry when first used
    }
}

function activate(context) {
    decorations.healthy  = makeDecorationType('healthy.svg');
    decorations.warning  = makeDecorationType('warning.svg');
    decorations.critical = makeDecorationType('critical.svg');

    loadHealth();
    watchHealthFile();

    // Decorate on open / switch / save
    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor(applyDecorations),
        vscode.workspace.onDidSaveTextDocument(doc => {
            const editor = vscode.window.activeTextEditor;
            if (editor && editor.document === doc) applyDecorations(editor);
        }),
        vscode.commands.registerCommand('pushkey.refreshHealth', () => {
            refreshAll();
            vscode.window.showInformationMessage('Pushkey: health data refreshed');
        }),
    );

    // Decorate already-open editors
    for (const editor of vscode.window.visibleTextEditors) {
        applyDecorations(editor);
    }
}

function deactivate() {
    clearReattachTimer();
    if (fileWatcher) fileWatcher.close();
    fileWatcher = null;
    for (const dec of Object.values(decorations)) dec.dispose();
}

module.exports = {
    activate,
    deactivate,
    _internals: {
        watchHealthFile,
        scheduleWatchReattach,
        clearReattachTimer,
    },
};
