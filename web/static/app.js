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

async function postJSON(url, payload = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

function setControlMessage(text) {
  el("control-msg").textContent = text;
}

function createMapRow(channelId = "", selectedSkill = "") {
  const list = el("channel-skill-list");
  const skillOptions = JSON.parse(list.dataset.skillOptions || "[]");
  const row = document.createElement("div");
  row.className = "map-row";

  const input = document.createElement("input");
  input.className = "map-channel";
  input.placeholder = "channel id";
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

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn-remove-map";
  btn.textContent = "remove";
  btn.addEventListener("click", () => {
    row.remove();
    syncChannelSkillHidden();
  });

  input.addEventListener("input", syncChannelSkillHidden);
  select.addEventListener("change", syncChannelSkillHidden);

  row.appendChild(input);
  row.appendChild(select);
  row.appendChild(btn);
  list.appendChild(row);
}

function syncChannelSkillHidden() {
  const rows = Array.from(document.querySelectorAll(".map-row"));
  const mapped = rows
    .map((row) => {
      const channel = row.querySelector(".map-channel")?.value?.trim() || "";
      const skill = row.querySelector(".map-skill")?.value?.trim() || "";
      return { channel, skill };
    })
    .filter((x) => x.channel && x.skill);
  el("channel-skills-hidden").value = mapped.map((x) => `${x.channel}:${x.skill}`).join(",");
  return mapped;
}

function updateBotStatus(bot) {
  const running = Boolean(bot && bot.running);
  el("bot-status").textContent = running ? "running" : "stopped";
  el("bot-pid").textContent = running ? String(bot.pid) : "-";
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

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();

    updateBotStatus(data.bot);
    hydrateSkillOptions(data.skill_options);

    el("db-exists").textContent = data.db_exists ? "ok" : "missing";
    el("total-events").textContent = data.total_events;
    el("total-users").textContent = data.total_users;
    el("replies-24h").textContent = data.bot_replies_24h;
    el("last-age").textContent = fmtAge(data.last_event_age_sec);
    el("db-path").textContent = data.error ? `db error: ${data.error}` : `db: ${data.db_path}`;

    const eventLines = (data.recent_events || []).map((e) => {
      const stamp = fmtTs(e.created_at);
      const msg = (e.content || "").replace(/\s+/g, " ").trim();
      return `[${stamp}] ${e.event_type} :: ${e.author_name} :: ${msg}`;
    });
    el("events-log").textContent = eventLines.join("\n");
    el("bot-log").textContent = (data.log_tail || []).join("\n");
  } catch (err) {
    el("events-log").textContent = `status fetch error: ${err}`;
  }
}

async function saveSettings() {
  const form = el("settings-form");
  const payload = Object.fromEntries(new FormData(form).entries());
  const rows = syncChannelSkillHidden().map((x) => ({ channel_id: x.channel, skill: x.skill }));
  payload.CHANNEL_SKILL_ROWS = rows;
  const msg = el("save-msg");
  msg.textContent = "saving...";
  const data = await postJSON("/api/settings", payload);
  if (!data.ok) {
    msg.textContent = "save failed";
    return false;
  }
  msg.textContent = `saved: ${data.updated_keys.join(", ")}`;
  return true;
}

async function onSubmit(ev) {
  ev.preventDefault();
  try {
    await saveSettings();
    await refreshStatus();
  } catch (err) {
    el("save-msg").textContent = `save error: ${err}`;
  }
}

async function actionBot(url, pendingText) {
  setControlMessage(pendingText);
  try {
    const data = await postJSON(url);
    setControlMessage(data.message || "done");
    updateBotStatus(data);
    await refreshStatus();
  } catch (err) {
    setControlMessage(`action error: ${err}`);
  }
}

async function saveAndRestart() {
  try {
    const ok = await saveSettings();
    if (!ok) return;
    await actionBot("/api/bot/restart", "restarting bot...");
  } catch (err) {
    setControlMessage(`save+restart error: ${err}`);
  }
}

el("settings-form").addEventListener("submit", onSubmit);
el("btn-start").addEventListener("click", () => actionBot("/api/bot/start", "starting bot..."));
el("btn-stop").addEventListener("click", () => actionBot("/api/bot/stop", "stopping bot..."));
el("btn-restart").addEventListener("click", () => actionBot("/api/bot/restart", "restarting bot..."));
el("btn-save-restart").addEventListener("click", saveAndRestart);
el("btn-add-map").addEventListener("click", () => createMapRow());

Array.from(document.querySelectorAll(".map-row")).forEach((row) => {
  row.querySelector(".btn-remove-map")?.addEventListener("click", () => {
    row.remove();
    syncChannelSkillHidden();
  });
  row.querySelector(".map-channel")?.addEventListener("input", syncChannelSkillHidden);
  row.querySelector(".map-skill")?.addEventListener("change", syncChannelSkillHidden);
});
syncChannelSkillHidden();

refreshStatus();
setInterval(refreshStatus, 4000);
