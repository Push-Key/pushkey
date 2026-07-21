let currentFilter = "all";
let currentHealth = null;

const STATUS_CLASSES = Object.freeze({
  healthy: "green",
  warning: "amber",
  critical: "red",
  unknown: "unknown",
});

function statusClass(status) {
  return STATUS_CLASSES[status] || "unknown";
}

function appendText(parent, text, className) {
  const element = document.createElement("div");
  if (className) element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

function renderOffline(list, title, detail) {
  const offline = document.createElement("div");
  offline.className = "offline";
  appendText(offline, title);
  if (detail) appendText(offline, detail, "offline-detail");
  list.appendChild(offline);
}

function renderList(health) {
  const list = document.getElementById("key-list");
  list.replaceChildren();
  if (!health) {
    renderOffline(list, "Pushkey not running", "Launch the Pushkey desktop app to see key health.");
    return;
  }

  const entries = Object.entries(health)
    .filter(([, value]) => currentFilter === "all" || value.status === currentFilter)
    .sort(([, a], [, b]) => {
      const order = { critical: 0, warning: 1, healthy: 2, unknown: 3 };
      return (order[a.status] ?? 3) - (order[b.status] ?? 3);
    });

  if (entries.length === 0) {
    renderOffline(list, "No keys match this filter.");
    return;
  }

  for (const [name, info] of entries) {
    const status = Object.hasOwn(STATUS_CLASSES, info.status) ? info.status : "unknown";
    const item = document.createElement("div");
    item.className = "item";
    const dot = document.createElement("div");
    dot.className = `dot ${status}`;
    const keyName = document.createElement("div");
    keyName.className = "key-name";
    keyName.textContent = name;
    keyName.title = name;
    const keyAge = document.createElement("div");
    keyAge.className = `key-age ${statusClass(status)}`;
    keyAge.textContent = info.days_old != null ? `${info.days_old}d` : "?";
    item.append(dot, keyName, keyAge);
    list.appendChild(item);
  }
}

function renderStats(counts) {
  document.getElementById("ct-healthy").textContent = counts?.healthy ?? "-";
  document.getElementById("ct-warning").textContent = counts?.warning ?? "-";
  document.getElementById("ct-critical").textContent = counts?.critical ?? "-";
}

function renderTimestamp(ts) {
  if (!ts) { document.getElementById("last-updated").textContent = "Not synced"; return; }
  const date = new Date(ts);
  document.getElementById("last-updated").textContent =
    "Updated " + date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function refresh() {
  const { health, counts, lastUpdated } = await chrome.storage.local.get(["health", "counts", "lastUpdated"]);
  currentHealth = health;
  renderStats(counts);
  renderList(health);
  renderTimestamp(lastUpdated);
}

document.querySelectorAll(".filter-btn").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach(candidate => candidate.classList.remove("active"));
    button.classList.add("active");
    currentFilter = button.dataset.filter;
    renderList(currentHealth);
  });
});

document.getElementById("refresh-btn").addEventListener("click", async () => {
  document.getElementById("refresh-btn").textContent = "...";
  await chrome.runtime.sendMessage({ action: "poll" }).catch(() => {});
  await new Promise(resolve => setTimeout(resolve, 1500));
  await refresh();
  document.getElementById("refresh-btn").textContent = "Refresh";
});

chrome.runtime.onMessage.addListener(message => {
  if (message.action === "healthUpdated") refresh();
});

refresh();
