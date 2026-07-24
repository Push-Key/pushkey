// Pushkey Browser Extension — background service worker
// Polls local health server every 5 minutes and updates badge.

const HEALTH_URL = "http://127.0.0.1:7654/health";
const POLL_MINUTES = 5;
const MAX_KEYS = 500;
const VALID_STATUSES = new Set(["healthy", "warning", "critical"]);

function sanitizeText(value, maxLength = 256) {
  if (value == null) return null;
  return String(value).slice(0, maxLength);
}

function sanitizeHealth(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return {};
  }

  const clean = {};
  for (const [rawName, rawInfo] of Object.entries(payload).slice(0, MAX_KEYS)) {
    if (!rawInfo || typeof rawInfo !== "object" || Array.isArray(rawInfo)) {
      continue;
    }
    const name = sanitizeText(rawName, 128);
    const status = VALID_STATUSES.has(rawInfo.status) ? rawInfo.status : "healthy";
    const daysOld =
      Number.isFinite(rawInfo.days_old) && rawInfo.days_old >= 0 ? rawInfo.days_old : null;
    clean[name] = {
      status,
      days_old: daysOld,
      provider: sanitizeText(rawInfo.provider, 64),
      category: sanitizeText(rawInfo.category, 64),
      first_used: sanitizeText(rawInfo.first_used, 64),
      last_used: sanitizeText(rawInfo.last_used, 64),
      created: sanitizeText(rawInfo.created, 64),
      rotated: sanitizeText(rawInfo.rotated, 64),
      rotation_count: Number.isInteger(rawInfo.rotation_count) ? rawInfo.rotation_count : 0,
    };
  }
  return clean;
}

async function fetchHealth() {
  try {
    const resp = await fetch(HEALTH_URL, { cache: "no-store" });
    if (!resp.ok) return null;
    return sanitizeHealth(await resp.json());
  } catch (_) {
    return null;
  }
}

function countByStatus(health) {
  const counts = { healthy: 0, warning: 0, critical: 0 };
  for (const info of Object.values(health)) {
    const s = info.status || "healthy";
    if (counts[s] !== undefined) counts[s]++;
  }
  return counts;
}

async function updateBadge() {
  const health = await fetchHealth();
  if (!health) {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#64748B" });
    await chrome.storage.local.set({ health: null, lastUpdated: null });
    return;
  }

  const counts = countByStatus(health);
  await chrome.storage.local.set({
    health,
    counts,
    lastUpdated: new Date().toISOString(),
  });

  if (counts.critical > 0) {
    chrome.action.setBadgeText({ text: String(counts.critical) });
    chrome.action.setBadgeBackgroundColor({ color: "#EF4444" });
  } else if (counts.warning > 0) {
    chrome.action.setBadgeText({ text: String(counts.warning) });
    chrome.action.setBadgeBackgroundColor({ color: "#F59E0B" });
  } else {
    chrome.action.setBadgeText({ text: "" });
  }
}

// Respond to popup refresh requests
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === "poll") {
    updateBadge().then(() => {
      chrome.runtime.sendMessage({ action: "healthUpdated" }).catch(() => {});
      sendResponse({ ok: true });
    });
    return true; // keep channel open for async response
  }
});

// Poll on install / startup
chrome.runtime.onInstalled.addListener(updateBadge);
chrome.runtime.onStartup.addListener(updateBadge);

// Poll every N minutes via alarms
chrome.alarms.create("pushkey-poll", { periodInMinutes: POLL_MINUTES });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "pushkey-poll") updateBadge();
});
