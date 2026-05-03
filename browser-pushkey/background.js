// Pushkey Browser Extension — background service worker
// Polls local health server every 5 minutes and updates badge.

const HEALTH_URL = "http://127.0.0.1:7654/health";
const POLL_MINUTES = 5;

async function fetchHealth() {
  try {
    const resp = await fetch(HEALTH_URL, { cache: "no-store" });
    if (!resp.ok) return null;
    return await resp.json();
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
