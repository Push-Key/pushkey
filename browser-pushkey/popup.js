let currentFilter = "all";
let currentHealth = null;

function statusClass(status) {
  return status === "critical" ? "red" : status === "warning" ? "amber" : "green";
}

function renderList(health) {
  const list = document.getElementById("key-list");
  list.innerHTML = "";
  if (!health) {
    list.innerHTML = `
      <div class="offline">
        <div class="icon">⚠️</div>
        <div>Pushkey not running</div>
        <div style="font-size:11px;margin-top:6px;color:#475569">
          Launch the Pushkey desktop app to see key health.
        </div>
      </div>`;
    return;
  }

  const entries = Object.entries(health)
    .filter(([, v]) => currentFilter === "all" || v.status === currentFilter)
    .sort(([, a], [, b]) => {
      const order = { critical: 0, warning: 1, healthy: 2 };
      return (order[a.status] ?? 3) - (order[b.status] ?? 3);
    });

  if (entries.length === 0) {
    list.innerHTML = `<div class="offline"><div>No keys match this filter.</div></div>`;
    return;
  }

  for (const [name, info] of entries) {
    const age = info.days_old != null ? `${info.days_old}d` : "?";
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = `
      <div class="dot ${info.status || "healthy"}"></div>
      <div class="key-name" title="${name}">${name}</div>
      <div class="key-age ${statusClass(info.status)}">${age}</div>`;
    list.appendChild(div);
  }
}

function renderStats(counts) {
  document.getElementById("ct-healthy").textContent = counts?.healthy ?? "—";
  document.getElementById("ct-warning").textContent = counts?.warning ?? "—";
  document.getElementById("ct-critical").textContent = counts?.critical ?? "—";
}

function renderTimestamp(ts) {
  if (!ts) { document.getElementById("last-updated").textContent = "Not synced"; return; }
  const d = new Date(ts);
  document.getElementById("last-updated").textContent =
    "Updated " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function refresh() {
  const { health, counts, lastUpdated } = await chrome.storage.local.get(["health","counts","lastUpdated"]);
  currentHealth = health;
  renderStats(counts);
  renderList(health);
  renderTimestamp(lastUpdated);
}

// Filter buttons
document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    renderList(currentHealth);
  });
});

// Refresh button — trigger background poll then re-read storage
document.getElementById("refresh-btn").addEventListener("click", async () => {
  document.getElementById("refresh-btn").textContent = "…";
  await chrome.runtime.sendMessage({ action: "poll" }).catch(() => {});
  await new Promise(r => setTimeout(r, 1500));
  await refresh();
  document.getElementById("refresh-btn").textContent = "Refresh";
});

// Handle poll message from background
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === "healthUpdated") refresh();
});

refresh();
