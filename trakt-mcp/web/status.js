"use strict";
const el = id => document.getElementById(id);
const text = (id, value) => { el(id).textContent = value; };
const ms = value => value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
const bytes = value => value == null ? "—" : value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1048576).toFixed(1)} MiB`;
function uptime(seconds) {
  const s = Math.floor(seconds), days = Math.floor(s / 86400), hours = Math.floor(s % 86400 / 3600), minutes = Math.floor(s % 3600 / 60);
  return `${days ? `${days}d ` : ""}${hours}h ${minutes}m`;
}
function rows(id, records, mapper, empty) {
  const body = el(id); body.replaceChildren();
  if (!records.length) {
    const row = document.createElement("tr"), cell = document.createElement("td");
    cell.colSpan = body.closest("table").querySelectorAll("th").length;
    cell.textContent = empty; cell.className = "empty"; row.append(cell); body.append(row); return;
  }
  records.forEach(record => {
    const row = document.createElement("tr");
    mapper(record).forEach((value, i) => {
      const cell = document.createElement("td"); cell.textContent = value;
      if (value === "ok") cell.className = "good";
      if (value === "error" || value === "timeout" || value === "cancelled") cell.className = "failed";
      if (String(value).startsWith("trakt_")) cell.className = "tool";
      row.append(cell);
    }); body.append(row);
  });
}
function cachePanel(name, data) {
  const box = document.createElement("div"), heading = document.createElement("div"), title = document.createElement("strong"), ratio = document.createElement("span");
  heading.className = "cache-title"; title.textContent = name;
  const total = (data.hits || 0) + (data.misses || 0), percent = total ? data.hits / total * 100 : null;
  ratio.textContent = !data.enabled ? "Disabled" : percent == null ? "No lookups" : `${percent.toFixed(1)}% hit rate`;
  heading.append(title, ratio);
  const meter = document.createElement("div"), fill = document.createElement("span");
  meter.className = "meter"; fill.style.width = `${percent || 0}%`; meter.append(fill);
  const summary = document.createElement("p"); summary.className = "cache-summary";
  summary.textContent = data.available === false ? "Cache status temporarily unavailable" : data.enabled ? `${data.entries} entries · ${bytes(data.response_bytes)} of data · ${data.hits || 0} hits / ${data.misses || 0} misses` : "Not enabled for this server";
  box.append(heading, meter, summary); return box;
}
function render(data) {
  const stats = data.metrics, tools = stats.tools;
  text("ready", stats.ready ? "Running" : "Starting"); el("ready").classList.toggle("ok", stats.ready);
  text("server-state", stats.ready ? "Ready for requests" : "Starting up"); text("uptime", `Uptime ${uptime(stats.uptime_seconds)}`);
  text("auth", data.authorization);
  text("calls", tools.calls.toLocaleString()); text("active", `${tools.active} in progress`);
  text("success", tools.success_percent == null ? "—" : `${tools.success_percent}%`); text("errors", `${tools.errors} failed or cancelled calls`);
  text("latency", ms(tools.average_ms)); text("p95", `95th percentile ${ms(tools.p95_ms)}`);
  el("caches").replaceChildren(cachePanel("Public metadata · disk", data.public_cache), cachePanel("Personal snapshots · RAM", data.personal_cache));
  rows("upstreams", Object.entries(stats.upstreams), ([name, value]) => [name === "oauth" ? "Trakt OAuth" : "Trakt API", value.requests, value.errors, value.rate_limits, ms(value.average_ms), bytes(value.bytes), data.cooldowns[name] ? `${data.cooldowns[name]} s` : "Clear"], "No upstream calls yet.");
  text("memory-label", stats.process.memory_kind === "current_rss" ? "Memory / current RSS" : "Memory / peak RSS");
  text("memory", bytes(stats.process.memory_bytes)); text("cpu", stats.process.cpu_percent == null ? "Sampling…" : `${stats.process.cpu_percent}%`);
  text("rejected", Object.values(stats.rejected_requests).reduce((sum, count) => sum + count, 0));
  rows("tools", stats.per_tool, r => [r.name, r.calls, r.errors, ms(r.average_ms), ms(r.p95_ms)], "No tools called yet. Connect your assistant to start.");
  rows("recent", stats.recent, r => [new Date(r.at).toLocaleTimeString(), r.tool, r.outcome, ms(r.duration_ms)], "Recent tool calls will appear here.");
  text("updated", `Last update ${new Date(stats.observed_at).toLocaleTimeString()} · statistics since ${new Date(stats.started_at).toLocaleString()}`);
}
let busy = false;
async function refresh() {
  if (busy || document.hidden) return;
  busy = true; el("refresh").disabled = true;
  const controller = new AbortController(), deadline = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch("./api/stats", {cache: "no-store", signal: controller.signal});
    if (!response.ok) throw new Error("Statistics unavailable");
    render(await response.json());
    text("connection", "Live statistics · automatic refresh is active"); el("connection").classList.remove("error");
  } catch (_) {
    text("connection", "Statistics unavailable. Existing numbers may be stale. Check that the add-on is running, then refresh."); el("connection").classList.add("error");
  } finally { clearTimeout(deadline); busy = false; el("refresh").disabled = false; }
}
el("refresh").addEventListener("click", refresh);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
setInterval(refresh, 10000); refresh();
