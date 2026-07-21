const vscode = require('vscode');
const path = require('path');
const os = require('os');
const { HealthWatcher, readHealthFile } = require('./health-contract');

const HEALTH_FILE = path.join(os.homedir(), '.pushkey', 'health.json');

let decorations = {};
let healthData = {};
let healthWatcher = null;

function makeDecorationType(iconFile) {
    return vscode.window.createTextEditorDecorationType({
        gutterIconPath: path.join(__dirname, 'icons', iconFile),
        gutterIconSize: '70%',
    });
}

function applyDecorations(editor) {
    if (!editor) return;
    const base = path.basename(editor.document.fileName);
    if (!base.startsWith('.env') && base !== '.env') return;

    const byStatus = { healthy: [], warning: [], critical: [] };
    for (let i = 0; i < editor.document.lineCount; i++) {
        const text = editor.document.lineAt(i).text;
        if (!text.trim() || text.trim().startsWith('#')) continue;
        const match = text.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=/);
        if (!match) continue;
        const keyName = match[1];
        const info = healthData[keyName];
        if (!info || !byStatus[info.status]) continue;
        byStatus[info.status].push({
            range: new vscode.Range(i, 0, i, 0),
            hoverMessage: buildHoverMessage(keyName, info),
        });
    }
    editor.setDecorations(decorations.healthy, byStatus.healthy);
    editor.setDecorations(decorations.warning, byStatus.warning);
    editor.setDecorations(decorations.critical, byStatus.critical);
}

function buildHoverMessage(keyName, info) {
    const md = new vscode.MarkdownString();
    md.appendMarkdown('**Pushkey**: ');
    md.appendText(info.status.toUpperCase());
    md.appendMarkdown('\n\n');
    md.appendCodeblock(keyName);
    if (info.provider !== null) {
        md.appendMarkdown('\n\nProvider: ');
        md.appendText(info.provider);
    }
    if (info.days_old !== null) {
        md.appendMarkdown('\n\nAge: ');
        md.appendText(String(info.days_old));
        md.appendText(' days');
    }
    if (info.status === 'critical') {
        md.appendMarkdown('\n\n**Rotation overdue. Open Pushkey to rotate.**');
    } else if (info.status === 'warning') {
        md.appendMarkdown('\n\nRotation recommended soon.');
    }
    return md;
}

function applyHealthResult(result) {
    healthData = result.state === 'available' ? result.keys : {};
    for (const editor of vscode.window.visibleTextEditors) applyDecorations(editor);
}

function refreshAll() {
    if (healthWatcher) healthWatcher.refresh();
}

function activate(context) {
    decorations.healthy = makeDecorationType('healthy.svg');
    decorations.warning = makeDecorationType('warning.svg');
    decorations.critical = makeDecorationType('critical.svg');
    healthWatcher = new HealthWatcher({
        healthFile: HEALTH_FILE,
        read: file => readHealthFile(file),
        onUpdate: applyHealthResult,
    });
    healthWatcher.start();

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
    for (const editor of vscode.window.visibleTextEditors) applyDecorations(editor);
}

function deactivate() {
    if (healthWatcher) healthWatcher.dispose();
    healthWatcher = null;
    healthData = {};
    for (const dec of Object.values(decorations)) dec.dispose();
}

module.exports = { activate, deactivate };
