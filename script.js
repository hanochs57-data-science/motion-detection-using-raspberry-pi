const $ = (id) => document.getElementById(id);

let range = "week";
let footageOnly = false;
let feedOn = false;
let lastSig = "";

const IMG_EXT = /\.(jpe?g|png|gif|webp)$/i;
const VID_EXT = /\.(mp4|webm|ogg|mov)$/i;

function esc(t) {
  const d = document.createElement("div");
  d.textContent = t;
  return d.innerHTML;
}

function dayLabel(ts) {
  const d = new Date(ts * 1000), t = new Date();
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const b = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  const diff = Math.round((b - a) / 864e5);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString([], {
    weekday: "short", day: "numeric", month: "short",
    year: diff > 300 ? "numeric" : undefined,
  });
}

const timeLabel = (ts) =>
  new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/* ---------- Live status ---------- */
async function refreshStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    $("statusPill").className = "overlay top-left " + (!s.armed ? "" : s.motion ? "alert" : "safe");
    $("statusText").textContent = !s.armed ? "Disarmed" : s.motion ? "MOTION DETECTED" : "All clear";
    $("armBtn").textContent = s.armed ? "Disarm" : "Arm";

    if (s.has_frame && !feedOn) {
      $("video").src = "/video_feed";
      $("video").hidden = false;
      $("noFeed").hidden = true;
      feedOn = true;
    }
  } catch (e) {
    $("statusText").textContent = "Offline";
  }
}

/* ---------- History ---------- */
async function refreshHistory() {
  try {
    const url = `/api/events?range=${range}` + (footageOnly ? "&footage=1" : "");
    const events = await (await fetch(url)).json();

    const sig = range + footageOnly + events.length + (events[0] ? events[0].id : "");
    if (sig === lastSig) return;          // nothing new, skip re-render
    lastSig = sig;

    const alerts = events.filter((e) => e.level === "alert").length;
    $("summary").textContent = `${alerts} detection${alerts === 1 ? "" : "s"} in this period`;

    if (!events.length) {
      $("list").innerHTML = '<div class="empty">No events in this period</div>';
      return;
    }

    let html = "", lastDay = "";
    events.forEach((e) => {
      const day = dayLabel(e.ts);
      if (day !== lastDay) { html += `<div class="day">${day}</div>`; lastDay = day; }

      let thumb = "";
      if (e.media && IMG_EXT.test(e.media)) thumb = `<img class="thumb" loading="lazy" src="/media/${e.media}">`;
      else if (e.media && VID_EXT.test(e.media)) thumb = '<div class="thumb clip">▶</div>';

      html += `<div class="item ${e.level} ${e.media ? "has-media" : ""}"
                    data-media="${e.media || ""}" data-cap="${esc(e.message)} · ${timeLabel(e.ts)}">
                 ${thumb}
                 <div><div class="msg">${esc(e.message)}</div>
                 <div class="time">${timeLabel(e.ts)}</div></div>
               </div>`;
    });
    $("list").innerHTML = html;
  } catch (e) {}
}

/* ---------- Viewer ---------- */
function openViewer(media, caption) {
  $("viewerBody").innerHTML = VID_EXT.test(media)
    ? `<video src="/media/${media}" controls autoplay></video>`
    : `<img src="/media/${media}">`;
  $("viewerCaption").textContent = caption;
  $("viewer").hidden = false;
}
function closeViewer() {
  $("viewer").hidden = true;
  $("viewerBody").innerHTML = "";
}

$("list").addEventListener("click", (ev) => {
  const item = ev.target.closest(".item.has-media");
  if (item) openViewer(item.dataset.media, item.dataset.cap);
});
$("viewer").addEventListener("click", (ev) => {
  if (ev.target.tagName !== "VIDEO") closeViewer();
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeViewer(); });

/* ---------- Controls ---------- */
$("tabs").addEventListener("click", (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  range = b.dataset.range;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  lastSig = "";
  refreshHistory();
});
$("footageOnly").onchange = (ev) => { footageOnly = ev.target.checked; lastSig = ""; refreshHistory(); };
$("sideToggle").onclick = () => document.body.classList.toggle("side-closed");
$("armBtn").onclick = async () => {
  await fetch("/api/arm", { method: "POST" });
  refreshStatus(); refreshHistory();
};

setInterval(() => { $("clock").textContent = new Date().toLocaleString(); }, 1000);
setInterval(refreshStatus, 1000);
setInterval(refreshHistory, 2000);
refreshStatus(); refreshHistory();
