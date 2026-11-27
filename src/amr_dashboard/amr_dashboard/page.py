"""Single-page UI for the dashboard (served by dashboard.py)."""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AMR Ops · Warehouse</title>
<style>
  :root {
    --bg: #0e1114; --panel: #161a1f; --panel-2: #1c2128; --line: #262c34; --text: #e6e9ed; --muted: #8b94a0;
    --amber: #f2a93b; --teal: #3cc5b4; --red: #e5615b; --green: #5cc27a; --blue: #5b8def; --violet: #a68bf0;
    --mono: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 system-ui, "Segoe UI", sans-serif; }
  header { display: flex; align-items: center; gap: 14px; padding: 12px 20px; border-bottom: 1px solid var(--line); }
  header h1 { margin: 0; font-size: 15px; font-weight: 600; letter-spacing: .02em; }
  header .tag { font: 11px var(--mono); color: var(--muted); border: 1px solid var(--line); padding: 2px 8px; border-radius: 99px; }
  header .spacer { flex: 1; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--red); display: inline-block; margin-right: 6px; }
  .dot.live { background: var(--green); box-shadow: 0 0 8px var(--green); }
  #conn { font: 12px var(--mono); color: var(--muted); }
  main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; padding: 16px 20px; }
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; }
  .panel h2 { margin: 0; padding: 10px 14px; font-size: 11px; font-weight: 600; letter-spacing: .12em;
              text-transform: uppercase; color: var(--muted); border-bottom: 1px solid var(--line); }
  #mapwrap { position: relative; padding: 12px; }
  canvas { width: 100%; display: block; border-radius: 6px; background: #0b0d10; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; padding: 0 14px 12px; font-size: 12px; color: var(--muted); }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
  .side { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .robot { padding: 14px; display: grid; gap: 12px; }
  .row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .label { color: var(--muted); font-size: 12px; }
  .val { font: 13px var(--mono); text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .state { font: 600 12px var(--mono); padding: 3px 10px; border-radius: 99px; background: var(--panel-2); text-transform: uppercase; }
  .state.idle { color: var(--muted); } .state.navigating { color: var(--teal); } .state.picking, .state.dropping { color: var(--amber); }
  .state.charging { color: var(--blue); } .state.error { color: var(--red); }
  .bar { height: 8px; background: var(--panel-2); border-radius: 99px; overflow: hidden; }
  .bar > div { height: 100%; background: var(--green); transition: width .4s, background .4s; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
  .chip { font: 12px var(--mono); padding: 2px 8px; border-radius: 6px; background: var(--panel-2); color: var(--amber); }
  form { display: flex; gap: 8px; padding: 12px 14px 6px; }
  input { flex: 1; min-width: 0; background: var(--panel-2); color: var(--text); border: 1px solid var(--line);
          border-radius: 8px; padding: 9px 11px; font: inherit; }
  input:focus { outline: none; border-color: var(--amber); }
  button { background: var(--amber); color: #1a1205; border: 0; border-radius: 8px; padding: 0 14px; font-weight: 600; cursor: pointer; }
  .examples { display: flex; gap: 6px; flex-wrap: wrap; padding: 4px 14px 12px; }
  .examples span { font-size: 12px; color: var(--muted); border: 1px solid var(--line); border-radius: 99px;
                   padding: 2px 9px; cursor: pointer; }
  .examples span:hover { color: var(--text); border-color: var(--muted); }
  #feed { list-style: none; margin: 0; padding: 6px 0; max-height: 330px; overflow-y: auto; }
  #feed li { display: grid; grid-template-columns: 58px 62px 1fr; gap: 8px; padding: 5px 14px; font-size: 12.5px; }
  #feed .t { font: 11px var(--mono); color: var(--muted); padding-top: 1px; }
  #feed .k { font: 600 10.5px var(--mono); text-transform: uppercase; letter-spacing: .06em; padding-top: 2px; }
  .k.you { color: var(--amber); } .k.intent { color: var(--violet); } .k.plan { color: var(--teal); }
  .k.robot { color: var(--muted); } .k.reply { color: var(--green); } .k.verifier { color: var(--red); } .k.tool { color: var(--blue); }
  .kpis { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
  .kpi { padding: 12px 14px; }
  .kpi .n { font: 600 24px var(--mono); }
  .kpi .n small { font-size: 13px; color: var(--muted); font-weight: 400; margin-left: 2px; }
  .kpi .d { color: var(--muted); font-size: 12px; margin-top: 2px; }
  @media (max-width: 980px) { main { grid-template-columns: 1fr; } .kpis { grid-template-columns: repeat(3, 1fr); } }
</style>
</head>
<body>
<header>
  <h1>Warehouse AMR · Operations</h1>
  <span class="tag" id="mapname">map</span>
  <span class="spacer"></span>
  <span id="conn"><span class="dot"></span>connecting</span>
</header>
<main>
  <section class="panel">
    <h2>Live map</h2>
    <div id="mapwrap"><canvas id="map"></canvas></div>
    <div class="legend">
      <span><i style="background:var(--amber)"></i>robot</span><span><i style="background:var(--teal)"></i>Nav2 plan</span>
      <span><i style="background:#d9772b"></i>rack pick face</span><span><i style="background:var(--green)"></i>packing</span>
      <span><i style="background:var(--blue)"></i>shipping</span><span><i style="background:#e8c547"></i>charger</span>
    </div>
  </section>
  <div class="side">
    <section class="panel">
      <h2>Robot</h2>
      <div class="robot">
        <div class="row"><span class="state idle" id="state">—</span><span class="val" id="near">—</span></div>
        <div>
          <div class="row"><span class="label">Battery</span><span class="val" id="batt">—</span></div>
          <div class="bar"><div id="battbar" style="width:0%"></div></div>
        </div>
        <div class="row"><span class="label">Carrying</span><span class="chips" id="cargo"></span></div>
        <div class="row"><span class="label">Mission</span><span class="val" id="mission">—</span></div>
        <div class="row"><span class="label">Pose</span><span class="val" id="pose">—</span></div>
      </div>
    </section>
    <section class="panel">
      <h2>Command</h2>
      <form id="cmd"><input id="text" placeholder="e.g. bring bolts and bearings to packing" autocomplete="off"><button>Send</button></form>
      <div class="examples" id="examples"></div>
    </section>
    <section class="panel">
      <h2>Activity</h2>
      <ul id="feed"></ul>
    </section>
  </div>
  <div class="kpis">
    <section class="panel kpi"><div class="n" id="k_m">—</div><div class="d">missions</div></section>
    <section class="panel kpi"><div class="n" id="k_s">—</div><div class="d">success rate</div></section>
    <section class="panel kpi"><div class="n" id="k_d">—</div><div class="d">distance driven</div></section>
    <section class="panel kpi"><div class="n" id="k_t">—</div><div class="d">avg mission time</div></section>
    <section class="panel kpi"><div class="n" id="k_l">—</div><div class="d">avg agent think time</div></section>
    <section class="panel kpi"><div class="n" id="k_r">—</div><div class="d">route saving vs one-at-a-time</div></section>
  </div>
</main>
<script>
const EX = ["bring bolts and bearings to packing", "brake pads and battery cells to shipping",
            "go to rack B2", "go charge", "how is the battery?"];
const COLORS = {shelf: "#d9772b", packing: "#5cc27a", shipping: "#5b8def", charger: "#e8c547", home: "#8b94a0"};
const $ = id => document.getElementById(id);
const cv = $("map"), ctx = cv.getContext("2d");
const img = new Image(); let imgReady = false, S = null;
img.onload = () => { imgReady = true; }; img.src = "/map.png";

EX.forEach(t => { const s = document.createElement("span"); s.textContent = t; s.onclick = () => send(t); $("examples").append(s); });
$("cmd").onsubmit = e => { e.preventDefault(); send($("text").value); $("text").value = ""; };
async function send(text) {
  if (!text.trim()) return;
  await fetch("/api/command", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text})});
  poll();
}

function toPx(x, y, m, k) { return [(x - m.origin[0]) / m.resolution * k, (m.height - (y - m.origin[1]) / m.resolution) * k]; }

function draw() {
  if (!S || !imgReady) return;
  const m = S.map, dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = w * m.height / m.width;
  if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); cv.style.height = h + "px"; }
  const k = cv.width / m.width;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.filter = "invert(1) brightness(0.55) contrast(1.6)";
  ctx.drawImage(img, 0, 0, cv.width, cv.height); ctx.filter = "none";
  const lw = Math.max(1.5, k * 0.6);
  // trail
  if (S.trail.length > 1) {
    ctx.strokeStyle = "rgba(242,169,59,.28)"; ctx.lineWidth = lw * 1.6; ctx.beginPath();
    S.trail.forEach(([x, y], i) => { const [px, py] = toPx(x, y, m, k); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.stroke();
  }
  // plan
  if (S.plan.length > 1 && S.status.state === "navigating") {
    ctx.strokeStyle = "#3cc5b4"; ctx.setLineDash([lw * 3, lw * 2]); ctx.lineWidth = lw * 1.3; ctx.beginPath();
    S.plan.forEach(([x, y], i) => { const [px, py] = toPx(x, y, m, k); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke(); ctx.setLineDash([]);
  }
  // stations
  ctx.font = `${Math.max(10, k * 4.2)}px system-ui`; ctx.textAlign = "center";
  S.stations.forEach(s => {
    const [px, py] = toPx(s.x, s.y, m, k), r = k * 3.2;
    ctx.fillStyle = COLORS[s.type] || "#888"; ctx.globalAlpha = .9;
    ctx.beginPath(); ctx.arc(px, py, r, 0, 7); ctx.fill(); ctx.globalAlpha = 1;
    ctx.fillStyle = "#cfd5dc"; ctx.fillText(s.name.replace("_station", "").replace("_dock", ""), px, py - r - 4);
  });
  // robot
  const st = S.status;
  if (st.x != null) {
    const [px, py] = toPx(st.x, st.y, m, k), a = -st.yaw_deg * Math.PI / 180, r = k * 6;
    ctx.save(); ctx.translate(px, py); ctx.rotate(a);
    ctx.shadowColor = "#f2a93b"; ctx.shadowBlur = 14; ctx.fillStyle = "#f2a93b";
    ctx.beginPath(); ctx.moveTo(r * 1.25, 0); ctx.lineTo(-r * .8, r * .8); ctx.lineTo(-r * .45, 0); ctx.lineTo(-r * .8, -r * .8); ctx.closePath(); ctx.fill();
    ctx.restore();
  }
}

function render() {
  const st = S.status || {};
  $("mapname").textContent = S.map.name;
  const s = $("state"); s.textContent = st.state || "offline"; s.className = "state " + (st.state || "error");
  $("near").textContent = st.nearest_station || "—";
  const b = st.battery_pct; $("batt").textContent = b == null ? "—" : b.toFixed(0) + "%";
  $("battbar").style.width = (b || 0) + "%";
  $("battbar").style.background = b < 25 ? "var(--red)" : b < 50 ? "var(--amber)" : "var(--green)";
  $("cargo").innerHTML = (st.carrying || []).length ? st.carrying.map(c => `<span class="chip">${c}</span>`).join("") : '<span class="val">empty</span>';
  $("mission").textContent = st.mission || "—";
  $("pose").textContent = st.x == null ? "—" : `${st.x.toFixed(2)}, ${st.y.toFixed(2)}  ${st.yaw_deg.toFixed(0)}°`;
  $("feed").innerHTML = S.events.map(e => `<li><span class="t">${e.t}</span><span class="k ${e.kind}">${e.kind}</span><span>${e.text.replace(/</g, "&lt;")}</span></li>`).join("");
  const K = S.kpis || {}, f = (v, u) => v == null ? "—" : `${v}<small>${u}</small>`;
  $("k_m").innerHTML = K.missions ?? "—"; $("k_s").innerHTML = f(K.success_rate, "%"); $("k_d").innerHTML = f(K.distance_m, "m");
  $("k_t").innerHTML = f(K.avg_mission_s, "s"); $("k_l").innerHTML = f(K.avg_agent_latency_s, "s"); $("k_r").innerHTML = f(K.route_saving_pct, "%");
  draw();
}

async function poll() {
  try {
    S = await (await fetch("/api/state")).json();
    $("conn").innerHTML = `<span class="dot live"></span>live · ${S.server_time}`;
    render();
  } catch (e) { $("conn").innerHTML = '<span class="dot"></span>disconnected'; }
}
setInterval(poll, 500); poll(); window.onresize = draw;
</script>
</body>
</html>
"""
