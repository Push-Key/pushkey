# Pushkey Browser Extension

Displays API key health status from your local Pushkey vault in Chrome or Firefox.

## How it works

The Pushkey desktop app runs a local HTTP server on `127.0.0.1:7654`. The extension polls `/health` every 5 minutes and shows critical/warning counts in the badge.

## Install (Chrome)

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select this `browser-pushkey/` folder

## Install (Firefox)

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select `manifest.json` from this folder

## Icons

Replace `icons/icon16.png`, `icons/icon48.png`, `icons/icon128.png` with real PNG icons.
You can convert `icons/icon.svg` using Inkscape or any SVG→PNG tool.

## Badge colors

- 🔴 Red number = critical keys (rotation overdue)
- 🟡 Yellow number = warning keys (rotation due soon)
- No badge = all keys healthy

## Deep link (future)

Clicking a key name will launch `pushkey://` URI to open the desktop app directly at that key.
