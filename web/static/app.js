function el(id) {
  return document.getElementById(id);
}

function fmtAge(sec) {
  if (sec === null || sec === undefined) return "-";
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  return `${Math.floor(sec / 3600)}h`;
}

function fmtTs(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString();
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const REFRESH_INTERVAL_MS = 4000;
let refreshTimer = null;
let lastChannelRows = [];
let channelFilterText = "";

async function postJSON(url, payload = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) {
    window.location.href = "/login";
    return { ok: false, error: "unauthorized" };
  }
  return res.json();
}

function setControlMessage(text) {
  const node = el("control-msg");
  if (node) node.textContent = text;
}

function createMapRow(channelId = "", selectedSkill = "", selectedProfile = "normal") {
  const list = el("channel-skill-list");
  const skillOptions = JSON.parse(list.dataset.skillOptions || "[]");
  const profileOptions = JSON.parse(list.dataset.profileOptions || "[]");
  const item = document.createElement("div");
  item.className = "map-item";
  const row = document.createElement("div");
  row.className = "map-row";

  const input = document.createElement("input");
  input.className = "map-channel";
  input.placeholder = "contoh: 123456789";
  input.value = channelId;

  const select = document.createElement("select");
  select.className = "map-skill";
  if (selectedSkill) {
    const first = document.createElement("option");
    first.value = selectedSkill;
    first.textContent = selectedSkill;
    select.appendChild(first);
  }
  skillOptions.forEach((skill) => {
    if (skill === selectedSkill) return;
    const opt = document.createElement("option");
    opt.value = skill;
    opt.textContent = skill;
    select.appendChild(opt);
  });

  const profile = document.createElement("select");
  profile.className = "map-profile";
  if (selectedProfile) {
    const first = document.createElement("option");
    first.value = selectedProfile;
    first.textContent = selectedProfile;
    profile.appendChild(first);
  }
  profileOptions.forEach((name) => {
    if (name === selectedProfile) return;
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    profile.appendChild(opt);
  });

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn-remove-map";
  btn.textContent = "Hapus";
  btn.addEventListener("click", () => {
    item.remove();
    syncChannelSkillHidden();
  });

  const customToggleWrap = document.createElement("label");
  customToggleWrap.className = "map-custom-toggle";
  const customEnabled = document.createElement("input");
  customEnabled.type = "checkbox";
  customEnabled.className = "map-custom-enabled";
  customToggleWrap.appendChild(customEnabled);
  customToggleWrap.appendChild(document.createTextNode("Custom Delay"));

  const customRow = document.createElement("div");
  customRow.className = "map-custom-row hidden-view";
  const customFields = [
    ["map-direct-min", "Direct Min"],
    ["map-direct-max", "Direct Max"],
    ["map-keyword-min", "Keyword Min"],
    ["map-keyword-max", "Keyword Max"],
    ["map-random-min", "Random Min"],
    ["map-random-max", "Random Max"],
  ];
  customFields.forEach(([cls, placeholder]) => {
    const input = document.createElement("input");
    input.className = cls;
    input.placeholder = placeholder;
    input.addEventListener("input", syncChannelSkillHidden);
    customRow.appendChild(input);
  });
  customEnabled.addEventListener("change", () => {
    customRow.classList.toggle("hidden-view", !customEnabled.checked);
    syncChannelSkillHidden();
  });

  input.addEventListener("input", syncChannelSkillHidden);
  select.addEventListener("change", syncChannelSkillHidden);
  profile.addEventListener("change", syncChannelSkillHidden);

  row.appendChild(input);
  row.appendChild(select);
  row.appendChild(profile);
  row.appendChild(customToggleWrap);
  row.appendChild(btn);
  item.appendChild(row);
  item.appendChild(customRow);
  list.appendChild(item);
}

function syncChannelSkillHidden() {
  const items = Array.from(document.querySelectorAll(".map-item"));
  const mapped = items
    .map((item) => {
      const channel = item.querySelector(".map-channel")?.value?.trim() || "";
      const skill = item.querySelector(".map-skill")?.value?.trim() || "";
      const profile = item.querySelector(".map-profile")?.value?.trim() || "normal";
      const customEnabled = !!item.querySelector(".map-custom-enabled")?.checked;
      const directMin = item.querySelector(".map-direct-min")?.value?.trim() || "";
      const directMax = item.querySelector(".map-direct-max")?.value?.trim() || "";
      const keywordMin = item.querySelector(".map-keyword-min")?.value?.trim() || "";
      const keywordMax = item.querySelector(".map-keyword-max")?.value?.trim() || "";
      const randomMin = item.querySelector(".map-random-min")?.value?.trim() || "";
      const randomMax = item.querySelector(".map-random-max")?.value?.trim() || "";
      return {
        channel,
        skill,
        profile,
        customEnabled,
        directMin,
        directMax,
        keywordMin,
        keywordMax,
        randomMin,
        randomMax,
      };
    })
    .filter((x) => x.channel && x.skill && x.profile);
  const channelIds = mapped.map((x) => x.channel);
  if (el("channel-ids-hidden")) {
    el("channel-ids-hidden").value = channelIds.join(",");
  }
  if (el("channel-skills-hidden")) {
    el("channel-skills-hidden").value = mapped.map((x) => `${x.channel}:${x.skill}`).join(",");
  }
  if (el("channel-profiles-hidden")) {
    el("channel-profiles-hidden").value = mapped.map((x) => `${x.channel}:${x.profile}`).join(",");
  }
  if (el("channel-custom-delays-hidden")) {
    el("channel-custom-delays-hidden").value = mapped
      .filter((x) => x.customEnabled)
      .map((x) => `${x.channel}:${x.directMin}-${x.directMax}|${x.keywordMin}-${x.keywordMax}|${x.randomMin}-${x.randomMax}`)
      .join(",");
  }
  return mapped;
}

function updateSettingsSummary() {
  const form = el("settings-form");
  if (!form) return;
  const aiModelsRaw = form.querySelector('[name="AI_MODELS"]')?.value?.trim() || "";
  const firstModel = aiModelsRaw.split(",").map((x) => x.trim()).filter(Boolean)[0] || "-";
  const defaultSkill = form.querySelector('[name="DEFAULT_SKILL"]')?.value?.trim() || "-";
  const smalltalk = form.querySelector('[name="SMALLTALK_REPLY_CHANCE"]')?.value?.trim() || "-";
  const keyword = form.querySelector('[name="KEYWORD_REPLY_CHANCE"]')?.value?.trim() || "-";
  const random = form.querySelector('[name="RANDOM_REPLY_CHANCE"]')?.value?.trim() || "-";
  const routingRows = syncChannelSkillHidden();

  const modelNode = el("summary-model");
  const channelNode = el("summary-channel-count");
  const skillNode = el("summary-default-skill");
  const styleNode = el("summary-reply-style");
  if (modelNode) modelNode.textContent = firstModel;
  if (channelNode) channelNode.textContent = String(routingRows.length);
  if (skillNode) skillNode.textContent = defaultSkill;
  if (styleNode) styleNode.textContent = `S:${smalltalk} K:${keyword} R:${random}`;
}

function updateBotStatus(bot) {
  const statusNode = el("bot-status");
  const pidNode = el("bot-pid");
  const statusMon = el("bot-status-monitoring");
  const pidMon = el("bot-pid-monitoring");
  const running = Boolean(bot && bot.running);
  if (statusNode) statusNode.textContent = running ? "running" : "stopped";
  if (pidNode) pidNode.textContent = running ? String(bot.pid) : "-";
  if (statusMon) statusMon.textContent = running ? "running" : "stopped";
  if (pidMon) pidMon.textContent = running ? String(bot.pid) : "-";
}

function hydrateSkillOptions(skillOptions) {
  const select = el("default-skill");
  if (!select) return;
  const current = select.value;
  const known = new Set(Array.from(select.options).map((opt) => opt.value));
  (skillOptions || []).forEach((skill) => {
    if (known.has(skill)) return;
    const opt = document.createElement("option");
    opt.value = skill;
    opt.textContent = skill;
    select.appendChild(opt);
  });
  if (current) select.value = current;
}

const DELAY_PRESETS = {
  fast: {
    DELAY_DIRECT_MIN: 8,
    DELAY_DIRECT_MAX: 16,
    DELAY_KEYWORD_MIN: 15,
    DELAY_KEYWORD_MAX: 35,
    DELAY_RANDOM_MIN: 20,
    DELAY_RANDOM_MAX: 45,
    hint: "Cepat: bot terasa lebih aktif dan responsif.",
  },
  normal: {
    DELAY_DIRECT_MIN: 16,
    DELAY_DIRECT_MAX: 30,
    DELAY_KEYWORD_MIN: 30,
    DELAY_KEYWORD_MAX: 90,
    DELAY_RANDOM_MIN: 45,
    DELAY_RANDOM_MAX: 120,
    hint: "Normal: seimbang, cocok untuk penggunaan umum.",
  },
  slow: {
    DELAY_DIRECT_MIN: 30,
    DELAY_DIRECT_MAX: 60,
    DELAY_KEYWORD_MIN: 60,
    DELAY_KEYWORD_MAX: 150,
    DELAY_RANDOM_MIN: 90,
    DELAY_RANDOM_MAX: 240,
    hint: "Santai: bot lebih jarang muncul, terasa lebih natural di chat ramai.",
  },
};

function currentDelayValues() {
  const keys = [
    "DELAY_DIRECT_MIN",
    "DELAY_DIRECT_MAX",
    "DELAY_KEYWORD_MIN",
    "DELAY_KEYWORD_MAX",
    "DELAY_RANDOM_MIN",
    "DELAY_RANDOM_MAX",
  ];
  const out = {};
  keys.forEach((k) => {
    const val = Number(el(`settings-form`).querySelector(`[name="${k}"]`)?.value || 0);
    out[k] = Number.isFinite(val) ? val : 0;
  });
  return out;
}

function detectDelayPreset() {
  const current = currentDelayValues();
  for (const [name, preset] of Object.entries(DELAY_PRESETS)) {
    const same = Object.keys(current).every((key) => current[key] === preset[key]);
    if (same) return name;
  }
  return "custom";
}

function applyDelayPreset(name) {
  if (name === "custom" || !DELAY_PRESETS[name]) return;
  const form = el("settings-form");
  const preset = DELAY_PRESETS[name];
  Object.keys(preset).forEach((key) => {
    if (key === "hint") return;
    const input = form.querySelector(`[name="${key}"]`);
    if (input) input.value = String(preset[key]);
  });
}

function updateDelayPresetUI() {
  const presetSelect = el("delay-preset");
  const hint = el("delay-preset-hint");
  if (!presetSelect || !hint) return;
  const selected = presetSelect.value;
  if (selected === "custom") {
    hint.textContent = "Custom: kamu atur manual nilai min-max delay.";
    return;
  }
  hint.textContent = DELAY_PRESETS[selected]?.hint || "Pilih preset untuk isi otomatis nilai delay.";
}

function renderChannelBreakdown(items) {
  const body = el("scope-summary-body");
  if (!body) return;
  const rows = Array.isArray(items) ? items : [];
  lastChannelRows = rows;
  const filter = channelFilterText.trim().toLowerCase();
  const filteredRows = filter
    ? rows.filter((item) => {
      const server = item.guild_id === null || item.guild_id === undefined ? "dm" : String(item.guild_id);
      const channel = String(item.channel_id || "");
      return server.toLowerCase().includes(filter) || channel.toLowerCase().includes(filter);
    })
    : rows;

  const rowCountNode = el("scope-row-count");
  if (rowCountNode) {
    rowCountNode.textContent = `${filteredRows.length}/${rows.length}`;
  }
  if (!filteredRows.length) {
    body.innerHTML = '<tr><td colspan="5">Belum ada data channel.</td></tr>';
    return;
  }

  body.innerHTML = filteredRows
    .map((item) => {
      const server = item.guild_id === null || item.guild_id === undefined ? "DM/Unknown" : String(item.guild_id);
      const channel = String(item.channel_id || "-");
      const total = String(item.total_events || 0);
      const replies = String(item.bot_replies_24h || 0);
      const lastTs = item.last_event_ts ? fmtTs(item.last_event_ts) : "-";
      return `<tr>
        <td>${escapeHtml(server)}</td>
        <td>${escapeHtml(channel)}</td>
        <td>${escapeHtml(total)}</td>
        <td>${escapeHtml(replies)}</td>
        <td>${escapeHtml(lastTs)}</td>
      </tr>`;
    })
    .join("");
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    if (res.status === 401) {
      window.location.href = "/login";
      return;
    }
    const data = await res.json();

    updateBotStatus(data.bot);
    hydrateSkillOptions(data.skill_options);

    const dbExists = el("db-exists");
    const totalEvents = el("total-events");
    const totalUsers = el("total-users");
    const replies24h = el("replies-24h");
    const lastAge = el("last-age");
    const dbPath = el("db-path");
    if (dbExists) dbExists.textContent = data.db_exists ? "ok" : "missing";
    if (totalEvents) totalEvents.textContent = data.total_events;
    if (totalUsers) totalUsers.textContent = data.total_users;
    if (replies24h) replies24h.textContent = data.bot_replies_24h;
    if (lastAge) lastAge.textContent = fmtAge(data.last_event_age_sec);
    if (dbPath) dbPath.textContent = data.error ? `db error: ${data.error}` : `db: ${data.db_path}`;
    renderChannelBreakdown(data.channel_breakdown);
    const lastEventNode = el("last-event-at");
    if (lastEventNode) lastEventNode.textContent = fmtTs(data.last_event_ts);

    const rows = Array.isArray(data.channel_breakdown) ? data.channel_breakdown : [];
    const top = rows
      .slice()
      .sort((a, b) => (Number(b.bot_replies_24h || 0) - Number(a.bot_replies_24h || 0)))[0];
    const topNode = el("top-channel-24h");
    if (topNode) {
      topNode.textContent = top ? `${top.channel_id} (${top.bot_replies_24h})` : "-";
    }
    const summaryNode = el("monitoring-summary");
    if (summaryNode) {
      summaryNode.textContent = `Update ${new Date().toLocaleTimeString()} • ${rows.length} channel terpantau`;
    }

    const eventLines = (data.recent_events || []).map((e) => {
      const stamp = fmtTs(e.created_at);
      const msg = (e.content || "").replace(/\s+/g, " ").trim();
      return `[${stamp}] ${e.event_type} :: ${e.author_name} :: ${msg}`;
    });
    const eventsLog = el("events-log");
    const botLog = el("bot-log");
    if (eventsLog) eventsLog.textContent = eventLines.join("\n");
    if (botLog) botLog.textContent = (data.log_tail || []).join("\n");
  } catch (err) {
    const eventsLog = el("events-log");
    if (eventsLog) {
      eventsLog.textContent = `status fetch error: ${err}`;
    }
  }
}

async function saveSettings() {
  const form = el("settings-form");
  if (!form) return false;
  const payload = Object.fromEntries(new FormData(form).entries());
  const rows = syncChannelSkillHidden().map((x) => ({
    channel_id: x.channel,
    skill: x.skill,
    profile: x.profile,
    custom_enabled: x.customEnabled ? "1" : "",
    direct_min: x.directMin,
    direct_max: x.directMax,
    keyword_min: x.keywordMin,
    keyword_max: x.keywordMax,
    random_min: x.randomMin,
    random_max: x.randomMax,
  }));
  payload.CHANNEL_ROUTE_ROWS = rows;
  const msg = el("save-msg");
  msg.textContent = "Menyimpan...";
  const data = await postJSON("/api/settings", payload);
  if (!data.ok) {
    msg.textContent = data.error ? `Gagal simpan: ${data.error}` : "Gagal simpan settings";
    return false;
  }
  msg.textContent = `Tersimpan: ${data.updated_keys.join(", ")}`;
  return true;
}

async function onSubmit(ev) {
  ev.preventDefault();
  try {
    await saveSettings();
    await refreshStatus();
  } catch (err) {
    const msg = el("save-msg");
    if (msg) msg.textContent = `save error: ${err}`;
  }
}

async function actionBot(url, pendingText) {
  setControlMessage(pendingText);
  try {
    const data = await postJSON(url);
    setControlMessage(data.message || "selesai");
    updateBotStatus(data);
    await refreshStatus();
  } catch (err) {
    setControlMessage(`Error action: ${err}`);
  }
}

async function saveAndRestart() {
  try {
    const ok = await saveSettings();
    if (!ok) return;
    await actionBot("/api/bot/restart", "restarting bot...");
  } catch (err) {
    setControlMessage(`Error save+restart: ${err}`);
  }
}

if (el("settings-form")) {
  el("settings-form").addEventListener("submit", onSubmit);
}
if (el("btn-start")) {
  el("btn-start").addEventListener("click", () => actionBot("/api/bot/start", "Menjalankan bot..."));
}
if (el("btn-stop")) {
  el("btn-stop").addEventListener("click", () => actionBot("/api/bot/stop", "Menghentikan bot..."));
}
if (el("btn-restart")) {
  el("btn-restart").addEventListener("click", () => actionBot("/api/bot/restart", "Restart bot..."));
}
if (el("btn-save-restart")) {
  el("btn-save-restart").addEventListener("click", saveAndRestart);
}
if (el("btn-add-map")) {
  el("btn-add-map").addEventListener("click", () => createMapRow("", "", "normal"));
}

Array.from(document.querySelectorAll(".map-row")).forEach((row) => {
  const item = row.closest(".map-item");
  row.querySelector(".btn-remove-map")?.addEventListener("click", () => {
    item?.remove();
    syncChannelSkillHidden();
  });
  row.querySelector(".map-channel")?.addEventListener("input", syncChannelSkillHidden);
  row.querySelector(".map-skill")?.addEventListener("change", syncChannelSkillHidden);
  row.querySelector(".map-profile")?.addEventListener("change", syncChannelSkillHidden);
  const enabled = item?.querySelector(".map-custom-enabled");
  const customRow = item?.querySelector(".map-custom-row");
  enabled?.addEventListener("change", () => {
    customRow?.classList.toggle("hidden-view", !enabled.checked);
    syncChannelSkillHidden();
  });
  item?.querySelectorAll(".map-custom-row input").forEach((input) => {
    input.addEventListener("input", syncChannelSkillHidden);
  });
});
if (el("channel-skills-hidden") && el("channel-ids-hidden") && el("channel-profiles-hidden") && el("channel-custom-delays-hidden")) {
  syncChannelSkillHidden();
}

const delayPreset = el("delay-preset");
if (delayPreset) {
  delayPreset.value = detectDelayPreset();
  updateDelayPresetUI();
  delayPreset.addEventListener("change", () => {
    applyDelayPreset(delayPreset.value);
    updateDelayPresetUI();
  });
  [
    "DELAY_DIRECT_MIN",
    "DELAY_DIRECT_MAX",
    "DELAY_KEYWORD_MIN",
    "DELAY_KEYWORD_MAX",
    "DELAY_RANDOM_MIN",
    "DELAY_RANDOM_MAX",
  ].forEach((name) => {
    const input = el("settings-form").querySelector(`[name="${name}"]`);
    input?.addEventListener("input", () => {
      delayPreset.value = detectDelayPreset();
      updateDelayPresetUI();
    });
  });
}

const hasStatusWidgets = !!el("bot-status") || !!el("events-log");
if (hasStatusWidgets) {
  refreshStatus();
}

function setActiveView(view, pushHistory = true) {
  const settingsView = el("view-settings");
  const monitoringView = el("view-monitoring");
  if (!settingsView || !monitoringView) return;

  const isSettings = view !== "monitoring";
  settingsView.classList.toggle("hidden-view", !isSettings);
  monitoringView.classList.toggle("hidden-view", isSettings);

  document.querySelectorAll(".top-nav a[data-view]").forEach((a) => {
    const active = a.dataset.view === (isSettings ? "settings" : "monitoring");
    a.classList.toggle("active", active);
  });

  if (pushHistory) {
    const nextPath = isSettings ? "/settings" : "/monitoring";
    if (window.location.pathname !== nextPath) {
      window.history.pushState({ view: isSettings ? "settings" : "monitoring" }, "", nextPath);
    }
  }
}

function setAutoRefresh(enabled) {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  if (enabled) {
    refreshTimer = setInterval(refreshStatus, REFRESH_INTERVAL_MS);
  }
}

document.querySelectorAll(".top-nav a[data-view]").forEach((a) => {
  a.addEventListener("click", (ev) => {
    ev.preventDefault();
    setActiveView(a.dataset.view || "settings", true);
  });
});

window.addEventListener("popstate", () => {
  const view = window.location.pathname.includes("monitoring") ? "monitoring" : "settings";
  setActiveView(view, false);
});

const initialView = document.body?.dataset?.initialView || "settings";
setActiveView(initialView, false);

const autoRefreshToggle = el("auto-refresh-toggle");
if (autoRefreshToggle) {
  autoRefreshToggle.addEventListener("change", () => {
    setAutoRefresh(autoRefreshToggle.checked);
  });
  setAutoRefresh(autoRefreshToggle.checked);
}

const refreshNowBtn = el("btn-refresh-now");
if (refreshNowBtn) {
  refreshNowBtn.addEventListener("click", refreshStatus);
}

const filterInput = el("channel-filter");
if (filterInput) {
  filterInput.addEventListener("input", () => {
    channelFilterText = filterInput.value || "";
    renderChannelBreakdown(lastChannelRows);
  });
}

if (el("settings-form")) {
  el("settings-form").addEventListener("input", updateSettingsSummary);
  updateSettingsSummary();
}
