let currentFilter = "all";
let currentHealth = null;

function statusClass(status) {
  return status === "critical" ? "red" : status === "warning" ? "amber" : "green";
}

function clearElement(element) {
  while (element.firstChild) {
    element.removeChild(element.firstChild);
  }
}

function appendTextElement(parent, tag, className, text) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

function renderList(health) {
  const list = document.getElementById("key-list");
  clearElement(list);

  if (!health) {
    const offline = appendTextElement(list, "div", "offline", "");
    appendTextElement(offline, "div", "icon", "!");
    appendTextElement(offline, "div", "", "Pushkey not running");
    const help = appendTextElement(
      offline,
      "div",
      "",
      "Launch the Pushkey desktop app to see key health."
    );
    help.style.fontSize = "11px";
    help.style.marginTop = "6px";
    help.style.color = "#475569";
    return;
  }

  const entries = Object.entries(health)
    .filter(([, v]) => currentFilter === "all" || v.status === currentFilter)
    .sort(([, a], [, b]) => {
      const order = { critical: 0, warning: 1, healthy: 2 };
      return (order[a.status] ?? 3) - (order[b.status] ?? 3);
    });

  if (entries.length === 0) {
    const offline = appendTextElement(list, "div", "offline", "");
    appendTextElement(offline, "div", "", "No keys match this filter.");
    return;
  }

  for (const [name, info] of entries) {
    const age = info.days_old != null ? `${info.days_old}d` : "?";
    const item = document.createElement("div");
    item.className = "item";
    appendTextElement(item, "div", `dot ${info.status || "healthy"}`, "");
    const nameElement = appendTextElement(item, "div", "key-name", name);
    nameElement.title = name;
    appendTextElement(item, "div", `key-age ${statusClass(info.status)}`, age);
    list.appendChild(item);
  }
}

function renderStats(counts) {
  document.getElementById("ct-healthy").textContent = counts?.healthy ?? "-";
  document.getElementById("ct-warning").textContent = counts?.warning ?? "-";
  document.getElementById("ct-critical").textContent = counts?.critical ?? "-";
}

function renderTimestamp(ts) {
  if (!ts) {
    document.getElementById("last-updated").textContent = "Not synced";
    return;
  }
  const d = new Date(ts);
  document.getElementById("last-updated").textContent =
    "Updated " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function refresh() {
  const { health, counts, lastUpdated } = await chrome.storage.local.get([
    "health",
    "counts",
    "lastUpdated",
  ]);
  currentHealth = health;
  renderStats(counts);
  renderList(health);
  renderTimestamp(lastUpdated);
}

document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    renderList(currentHealth);
  });
});

document.getElementById("refresh-btn").addEventListener("click", async () => {
  document.getElementById("refresh-btn").textContent = "...";
  await chrome.runtime.sendMessage({ action: "poll" }).catch(() => {});
  await new Promise((resolve) => setTimeout(resolve, 1500));
  await refresh();
  document.getElementById("refresh-btn").textContent = "Refresh";
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === "healthUpdated") {
    refresh();
  }
});

refresh();
