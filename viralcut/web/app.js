"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const PLATFORMS = [
  ["tiktok", "TikTok"], ["instagram", "Reels"], ["youtube", "Shorts"], ["x", "X"], ["linkedin", "LinkedIn"],
];
// General best-practice posting slots (local time): [hour, minute, preferred weekdays (0=Sun)]
const BEST_TIMES = {
  tiktok: [19, 0, [2, 4, 5]], instagram: [11, 0, [1, 3, 5]], youtube: [15, 0, [4, 5, 6]],
  x: [9, 0, [2, 3, 4]], linkedin: [8, 30, [2, 3, 4]],
};
const STEP_ORDER = ["ingest", "transcribe", "analyze", "copywrite", "render", "done"];

const state = { tab: "link", min: 20, max: 60, res: 720, style: "bold", job: null, poll: null, sched: null };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) node.append(c instanceof Node ? c : document.createTextNode(String(c ?? "")));
  return node;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 2200);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied to clipboard ✓"); }
  catch { toast("Copy failed. Select the text manually."); }
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
    throw new Error(detail);
  }
  return res.json();
}

const fileUrl = (job, name) => `/api/jobs/${job.id}/files/${name}`;
const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/* ---------------- create view ---------------- */

async function loadConfig() {
  try {
    const cfg = await api("/api/config");
    const chips = $("#statusChips");
    chips.replaceChildren(
      el("span", { class: `chip ${cfg.ai ? "ok" : "off"}` }, cfg.ai ? `🧠 Claude · ${cfg.model}` : "🧠 Offline AI mode"),
      el("span", { class: `chip ${cfg.whisper ? "ok" : "off"}` }, cfg.whisper ? "🎙️ Whisper ready" : "🎙️ No Whisper"),
      el("span", { class: `chip ${cfg.ffmpeg ? "ok" : "off"}` }, cfg.ffmpeg ? "🎞️ FFmpeg" : "⚠️ FFmpeg missing"),
    );
    if (!cfg.ai) $("#useAi").parentElement.title = "Add your Claude API key in Settings to enable Claude";
  } catch { /* server status is decorative */ }
}

async function openSettings() {
  $("#settingsError").classList.add("hidden");
  try {
    const s = await api("/api/settings");
    $("#apiKey").value = "";
    $("#apiKey").placeholder = s.has_key ? "Key saved. Paste a new one to replace it" : "sk-ant-…";
    $("#keyHint").textContent = s.has_key ? `· saved (${s.key_hint})` : "· not set";
    $("#whisperModel").value = s.whisper_model;
    $("#removeKey").classList.toggle("hidden", !s.has_key);
    $("#settingsDialog").showModal();
  } catch (ex) { toast(ex.message); }
}

async function saveSettings(body) {
  try {
    await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("#settingsDialog").close();
    toast("Settings saved");
    loadConfig();
  } catch (ex) {
    $("#settingsError").textContent = ex.message;
    $("#settingsError").classList.remove("hidden");
  }
}

function bindForm() {
  $$(".tab").forEach((b) => b.addEventListener("click", () => {
    state.tab = b.dataset.tab;
    $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== state.tab));
  }));
  const segment = (root, fn) => $$("button", root).forEach((b) => b.addEventListener("click", () => {
    $$("button", root).forEach((x) => x.classList.toggle("on", x === b));
    fn(b.dataset);
  }));
  segment($("#lengthSeg"), (d) => { state.min = +d.min; state.max = +d.max; });
  segment($("#resSeg"), (d) => { state.res = +d.res; });
  segment($("#styleSeg"), (d) => { state.style = d.style; });
  $("#clipCount").addEventListener("input", (e) => { $("#countVal").textContent = e.target.value; });

  const drop = $("#dropZone");
  const file = $("#fileInput");
  const showFile = () => {
    const f = file.files[0];
    if (f) $("#dropText").replaceChildren(el("strong", {}, f.name), el("br"), el("small", {}, `${(f.size / 1e6).toFixed(1)} MB · ready`));
  };
  file.addEventListener("change", showFile);
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) { file.files = e.dataTransfer.files; showFile(); }
  });

  $("#jobForm").addEventListener("submit", submitJob);
}

async function submitJob(e) {
  e.preventDefault();
  const err = $("#formError");
  err.classList.add("hidden");
  const fd = new FormData();
  if (state.tab === "link") {
    const url = $("#urlInput").value.trim();
    if (!url) return showFormError("Paste a video link first.");
    fd.append("url", url);
  } else {
    const f = $("#fileInput").files[0];
    if (!f) return showFormError("Choose a video file first.");
    fd.append("file", f);
  }
  const subs = $("#subsInput").files[0];
  if (subs) fd.append("subtitles", subs);
  fd.append("settings", JSON.stringify({
    clip_count: +$("#clipCount").value, min_len: state.min, max_len: state.max, layout: $("#layout").value,
    caption_style: state.style, show_hook: $("#showHook").checked, use_ai: $("#useAi").checked, resolution: state.res,
  }));
  const btn = $("#submitBtn");
  btn.disabled = true;
  btn.textContent = state.tab === "upload" ? "Uploading…" : "Starting…";
  try {
    const job = await api("/api/jobs", { method: "POST", body: fd });
    location.hash = job.id;
  } catch (ex) {
    showFormError(ex.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "⚡ Generate viral clips";
  }
}

function showFormError(msg) {
  const err = $("#formError");
  err.textContent = msg;
  err.classList.remove("hidden");
}

async function loadRecent() {
  const jobs = await api("/api/jobs").catch(() => []);
  $("#recentWrap").classList.toggle("hidden", !jobs.length);
  $("#recent").replaceChildren(...jobs.slice(0, 12).map((j) => {
    const thumb = j.clips && j.clips[0] ? el("img", { src: fileUrl(j, j.clips[0].thumb), alt: "" }) : el("div", { class: "ph" });
    const label = j.status === "done" ? `${j.clips.length} shorts` : j.status === "error" ? "failed" : `${Math.round(j.progress * 100)}% · ${j.step}`;
    return el("div", { class: "recent-item", onclick: () => { location.hash = j.id; } },
      thumb, el("div", {}, el("b", {}, j.title || "Untitled"), el("small", {}, `${label} · ${new Date(j.created * 1000).toLocaleDateString()}`)));
  }));
}

/* ---------------- job view ---------------- */

async function openJob(id) {
  $("#createView").classList.add("hidden");
  $("#jobView").classList.remove("hidden");
  $("#clips").replaceChildren();
  state.renderedClips = 0;
  clearInterval(state.poll);
  const tick = async () => {
    try {
      const job = await api(`/api/jobs/${id}`);
      state.job = job;
      renderJob(job);
      if (job.status === "done" || job.status === "error") clearInterval(state.poll);
    } catch (ex) {
      clearInterval(state.poll);
      $("#jobTitle").textContent = "Project not found";
      $("#jobError").textContent = ex.message;
      $("#jobError").classList.remove("hidden");
    }
  };
  await tick();
  state.poll = setInterval(tick, 1500);
}

function renderJob(job) {
  $("#jobTitle").textContent = job.title || job.source;
  const meta = [job.duration ? `${fmtTime(job.duration)} source` : "", job.engine && `AI: ${job.engine}`,
    job.transcript_source && `Transcript: ${job.transcript_source}`].filter(Boolean);
  $("#jobMeta").textContent = meta.join("  ·  ");
  $("#zipBtn").href = `/api/jobs/${job.id}/export.zip`;
  $("#zipBtn").classList.toggle("hidden", !job.clips.length);

  const running = job.status !== "done";
  $("#progressCard").classList.toggle("hidden", !running);
  const cur = STEP_ORDER.indexOf(job.step);
  $$("#steps li").forEach((li) => {
    const i = STEP_ORDER.indexOf(li.dataset.step);
    li.classList.toggle("done", i < cur || job.status === "done");
    li.classList.toggle("active", i === cur && job.status === "running");
  });
  $("#bar").style.width = `${Math.round(job.progress * 100)}%`;
  $("#progressMsg").textContent = job.status === "queued" ? "Waiting in queue…" : job.message;
  $("#jobError").classList.toggle("hidden", job.status !== "error");
  $("#jobError").textContent = job.error ? `Something went wrong: ${job.error}` : "";

  $("#summaryCard").classList.toggle("hidden", !(job.status === "done" && job.long_form_post));
  $("#longPost").textContent = job.long_form_post;

  // append clips as they finish rendering (keeps playing videos untouched)
  for (let i = state.renderedClips; i < job.clips.length; i++) $("#clips").append(clipCard(job, job.clips[i]));
  state.renderedClips = job.clips.length;
  renderSchedule(job);
}

function scoreClass(s) { return s >= 85 ? "hot" : s >= 70 ? "good" : "ok"; }

function clipCard(job, clip) {
  let platform = "tiktok";
  const postText = el("p", { class: "post-text" });
  const tags = el("div", { class: "tags" });
  const showPost = () => {
    postText.textContent = clip.posts[platform] || "";
    tags.replaceChildren(...(clip.hashtags[platform] || []).map((t) => el("span", {}, t)));
  };
  const tabs = el("div", { class: "ptabs" }, PLATFORMS.map(([key, label]) => el("button", {
    type: "button", class: key === platform ? "on" : "",
    onclick: (e) => { platform = key; $$("button", tabs).forEach((b) => b.classList.toggle("on", b === e.target)); showPost(); },
  }, label)));
  showPost();
  const fullPost = () => `${clip.posts[platform] || ""}\n\n${(clip.hashtags[platform] || []).join(" ")}`.trim();
  const signals = Object.entries(clip.signals || {}).slice(0, 8).map(([k, v]) =>
    el("div", { class: "sig" }, k, el("div", {}, el("i", { style: `width:${Math.round(v * 100)}%` }))));

  return el("article", { class: "clip" },
    el("div", { class: "clip-video" },
      el("video", { src: fileUrl(job, clip.video), poster: fileUrl(job, clip.thumb), controls: "", preload: "none", playsinline: "" }),
      el("span", { class: `score ${scoreClass(clip.score)}` }, `🔥 ${Math.round(clip.score)}`),
      el("span", { class: "dur" }, `${clip.duration}s · ${fmtTime(clip.start)}`)),
    el("div", { class: "clip-body" },
      el("h3", {}, clip.title),
      el("p", { class: "reason" }, `💡 ${clip.reason}`),
      el("div", { class: "signals" }, signals),
      tabs,
      el("div", { class: "post-box" }, postText, tags,
        el("div", { class: "post-actions" },
          el("button", { class: "btn small", type: "button", onclick: () => copy(fullPost()) }, "📋 Copy post + tags"),
          el("button", { class: "btn small", type: "button", onclick: () => copy((clip.hashtags[platform] || []).join(" ")) }, "# Copy tags"))),
      clip.transcript ? el("details", { class: "tx" }, el("summary", {}, "Transcript"), el("p", { class: "transcript" }, clip.transcript)) : ""),
    el("div", { class: "clip-foot" },
      el("a", { class: "btn", href: fileUrl(job, clip.video), download: `${clip.id}.mp4` }, "⬇ Download"),
      el("button", { class: "btn primary", type: "button", onclick: () => openSchedule(job, clip, platform, fullPost()) }, "🗓️ Schedule")));
}

/* ---------------- scheduling ---------------- */

function nextBestTime(platform) {
  const [h, m, days] = BEST_TIMES[platform];
  const d = new Date();
  for (let i = 0; i < 8; i++) {
    const c = new Date(d.getFullYear(), d.getMonth(), d.getDate() + i, h, m);
    if (c > d && days.includes(c.getDay())) return c;
  }
  return new Date(d.getTime() + 86400000);
}

const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

function openSchedule(job, clip, platform, caption) {
  state.sched = { job, clip, platform };
  $("#schedClipTitle").textContent = clip.title;
  $("#schedCaption").value = caption;
  const wrap = $("#schedPlatforms");
  const setPlatform = (key) => {
    state.sched.platform = key;
    $$("button", wrap).forEach((b) => b.classList.toggle("on", b.dataset.p === key));
    $("#schedTime").value = toLocalInput(nextBestTime(key));
    $("#bestTime").textContent = "· suggested peak time";
    $("#schedCaption").value = `${clip.posts[key] || ""}\n\n${(clip.hashtags[key] || []).join(" ")}`.trim();
  };
  wrap.replaceChildren(...PLATFORMS.map(([key, label]) =>
    el("button", { type: "button", "data-p": key, onclick: () => setPlatform(key) }, label)));
  setPlatform(platform);
  $("#schedDialog").showModal();
}

async function saveSchedule(e) {
  if (e.submitter && e.submitter.value !== "save") return;
  e.preventDefault();
  const { job, clip, platform } = state.sched;
  try {
    const schedule = await api(`/api/jobs/${job.id}/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clip_id: clip.id, platform, time: $("#schedTime").value, caption: $("#schedCaption").value }),
    });
    state.job.schedule = schedule;
    renderSchedule(state.job);
    $("#schedDialog").close();
    toast("Added to your posting schedule");
  } catch (ex) { toast(ex.message); }
}

function renderSchedule(job) {
  $("#scheduleCard").classList.toggle("hidden", !job.schedule.length);
  $("#icsBtn").href = `/api/jobs/${job.id}/schedule.ics`;
  const label = Object.fromEntries(PLATFORMS);
  $("#scheduleList").replaceChildren(...job.schedule.map((s, i) => {
    const clip = job.clips.find((c) => c.id === s.clip_id);
    return el("li", {},
      el("b", {}, label[s.platform] || s.platform),
      el("small", {}, new Date(s.time).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })),
      el("span", {}, clip ? clip.title : s.clip_id),
      el("button", { class: "btn small", type: "button", onclick: () => copy(s.caption) }, "Copy"),
      el("button", { class: "btn small ghost", type: "button", onclick: async () => {
        state.job.schedule = await api(`/api/jobs/${job.id}/schedule/${i}`, { method: "DELETE" });
        renderSchedule(state.job);
      } }, "✕"));
  }));
}

/* ---------------- routing ---------------- */

function route() {
  const id = location.hash.slice(1);
  if (id) return openJob(id);
  clearInterval(state.poll);
  $("#jobView").classList.add("hidden");
  $("#createView").classList.remove("hidden");
  loadRecent();
}

$("#backBtn").addEventListener("click", () => { location.hash = ""; });
$("#copyLong").addEventListener("click", () => copy($("#longPost").textContent));
$("#schedForm").addEventListener("submit", saveSchedule);
$("#settingsBtn").addEventListener("click", openSettings);
$("#removeKey").addEventListener("click", () => saveSettings({ anthropic_api_key: "" }));
$("#settingsForm").addEventListener("submit", (e) => {
  if (e.submitter && e.submitter.value !== "save") return;
  e.preventDefault();
  const body = { whisper_model: $("#whisperModel").value };
  if ($("#apiKey").value.trim()) body.anthropic_api_key = $("#apiKey").value.trim();
  saveSettings(body);
});
window.addEventListener("hashchange", route);
bindForm();
loadConfig();
route();
