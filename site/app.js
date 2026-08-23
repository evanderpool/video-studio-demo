(async function () {
  const index = await (await fetch("data/index.json")).json();
  const tpl = document.getElementById("bay-tpl");
  const root = document.getElementById("bays");
  const fmt = (s) => s.toFixed(2).padStart(5, "0");

  // masthead stats
  const raw = index.reduce((a, v) => a + v.stats.raw_duration_s, 0);
  const out = index.reduce((a, v) => a + v.stats.output_duration_s, 0);
  const qaPass = index.filter((v) => v.qa.sync_ok && v.qa.black_ok).length;
  const S = (k) => document.querySelector(`[data-stat="${k}"]`);
  countUp(S("count"), index.length, 0);
  countUp(S("raw"), raw, 0);
  countUp(S("out"), out, 0);
  countUp(S("kept"), (out / raw) * 100, 0);
  S("qa").textContent = `${qaPass}/${index.length}`;

  // gallery grid -> click opens one trace bay under the grid
  const grid = document.getElementById("grid");
  const cards = index.map((item, i) => {
    const c = document.createElement("button");
    c.className = "card"; c.type = "button";
    c.innerHTML = `<span class="idx"></span><video muted playsinline preload="metadata"></video><span class="play">▶</span>
      <div class="meta"><b></b><span></span></div>`;
    c.querySelector(".idx").textContent = String(i + 1).padStart(2, "0");
    c.querySelector("video").src = `data/${item.slug}/output.mp4#t=0.5`;
    c.querySelector("b").textContent = item.title;
    c.querySelector(".meta span").innerHTML = `${item.stats.raw_duration_s.toFixed(0)}s <i>→</i> ${item.stats.output_duration_s.toFixed(0)}s · ${item.stats.segments} beats · ${item.stats.overlays} pops`;
    c.addEventListener("click", () => openBay(i));
    c.addEventListener("mouseenter", () => { const v = c.querySelector("video"); v.currentTime = 0; v.play().catch(() => {}); });
    c.addEventListener("mouseleave", () => { const v = c.querySelector("video"); v.pause(); v.currentTime = 0.5; });
    grid.appendChild(c);
    return c;
  });

  const bayCache = {};
  async function openBay(i, scroll = true) {
    const item = index[i];
    cards.forEach((c, n) => c.classList.toggle("open", n === i));
    if (!bayCache[i]) {
      const [edl, dec] = await Promise.all([
        fetch(`data/${item.slug}/edl.json`).then((r) => r.json()),
        fetch(`data/${item.slug}/decision.json`).then((r) => r.json()),
      ]);
      bayCache[i] = buildBay(i, `data/${item.slug}/`, edl, dec);
    }
    root.querySelectorAll("video").forEach((v) => v.pause());
    root.replaceChildren(bayCache[i]);
    bayCache[i].style.animation = "none"; void bayCache[i].offsetWidth; bayCache[i].style.animation = "";
    if (scroll) bayCache[i].scrollIntoView({ behavior: "smooth", block: "start" });
  }
  openBay(0, false);

  tryIt();

  function buildBay(i, base, edl, dec, indexLabel) {
    const el = tpl.content.firstElementChild.cloneNode(true);
    el.style.animationDelay = `${i * 0.08}s`;
    const q = (s) => el.querySelector(s);
    q(".index").textContent = indexLabel || String(i + 1).padStart(2, "0");
    q(".title").textContent = dec.title;
    q(".theme").textContent = dec.theme || "";
    q(".raw").textContent = dec.stats.raw_duration_s.toFixed(1);
    q(".out").textContent = dec.stats.output_duration_s.toFixed(1);

    const video = q("video");
    video.src = `${base}output.mp4`;

    // output-timeline positions for each range
    let t = 0;
    const beats = edl.ranges.map((r) => {
      const dur = r.end - r.start;
      const b = { ...r, outStart: t, outEnd: t + dur };
      t += dur;
      return b;
    });

    // cut map over raw timeline
    const cm = q(".cutmap");
    const rawDur = dec.stats.raw_duration_s;
    cm.innerHTML = '<div class="ticks"></div>';
    const keepEls = beats.map((b) => {
      const d = document.createElement("div");
      d.className = "keep";
      d.style.left = `${(b.start / rawDur) * 100}%`;
      d.style.width = `${((b.end - b.start) / rawDur) * 100}%`;
      d.title = `${fmt(b.start)}–${fmt(b.end)}s raw`;
      cm.appendChild(d);
      return d;
    });
    const legend = document.createElement("div");
    legend.className = "cutmap-legend";
    legend.innerHTML = `<span>00.00</span><span>${dec.stats.segments} spans kept · ${Math.round(dec.stats.kept_ratio * 100)}% of ${rawDur.toFixed(1)}s</span><span>${rawDur.toFixed(1)}</span>`;
    cm.after(legend);

    // beat list
    const ol = q(".beats");
    const beatEls = beats.map((b) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="t">${fmt(b.outStart)}</span><span class="beat"></span><span class="tag ${b.keep === "verbatim" ? "verbatim" : ""}">${b.keep === "verbatim" ? "verbatim" : b.motion || ""}</span>`;
      li.querySelector(".beat").textContent = b.beat;
      li.addEventListener("click", () => { video.currentTime = b.outStart + 0.01; video.play(); });
      ol.appendChild(li);
      return li;
    });

    // pops
    const pops = q(".pops");
    const popEls = (edl.overlays || []).map((o) => {
      const s = document.createElement("span");
      s.className = "pop";
      s.innerHTML = `<span></span><small>@${fmt(o.start_in_output)}</small>`;
      s.firstChild.textContent = o.text;
      s.addEventListener("click", () => { video.currentTime = o.start_in_output; video.play(); });
      pops.appendChild(s);
      return s;
    });

    // reasoning
    q(".reason").textContent = dec.brain_reason || dec.theme || "";
    q(".notes").textContent = dec.edit_notes || "";
    const vs = q(".variants");
    if (dec.other_variants?.length) {
      const h = document.createElement("p");
      h.className = "label";
      h.textContent = "Alternate cuts the brain also produced";
      vs.appendChild(h);
      for (const v of dec.other_variants) {
        const d = document.createElement("div");
        d.innerHTML = `<b></b><span></span> <em style="color:var(--ink-3);font-style:normal"></em>`;
        d.querySelector("b").textContent = v.style;
        d.querySelector("span").textContent = v.reason;
        d.querySelector("em").textContent = `· ${v.duration}s`;
        vs.appendChild(d);
      }
    }

    // qa
    const qa = q(".qa");
    const row = (label, val, cls) => { const li = document.createElement("li"); li.className = cls; li.textContent = `${label} ${val}`; qa.appendChild(li); };
    row("A/V sync", dec.qa.sync_ok ? "OK" : "FAIL", dec.qa.sync_ok ? "ok" : "bad");
    row("black frames", dec.qa.black_ok ? "none" : "FOUND", dec.qa.black_ok ? "ok" : "bad");
    row("drift", `${dec.qa.av_drift}s`, "neutral");
    row("compliance drops", String(dec.compliance_dropped?.length || 0), "neutral");
    if (dec.qa_frames.length) row("pops verified", `${dec.qa_frames.length}/${dec.stats.overlays}`, dec.qa_frames.length === dec.stats.overlays ? "ok" : "neutral");
    const fr = q(".frames");
    dec.qa_frames.forEach((f, n) => {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = `${base}${f}`;
      img.alt = `Frame where pop ${n + 1} renders`;
      fr.appendChild(img);
    });
    const sheet = q(".sheet");
    if (dec.has_contact_sheet) sheet.querySelector("img").src = `${base}contact_sheet.jpg`;
    else sheet.remove();

    // live sync
    const cur = q(".cur"), beatNow = q(".beat-now");
    video.addEventListener("timeupdate", () => {
      const ct = video.currentTime;
      cur.textContent = fmt(ct);
      let liveBeat = "";
      beats.forEach((b, n) => {
        const live = ct >= b.outStart && ct < b.outEnd;
        beatEls[n].classList.toggle("live", live);
        keepEls[n].classList.toggle("live", live);
        if (live) liveBeat = b.beat;
      });
      beatNow.textContent = liveBeat;
      (edl.overlays || []).forEach((o, n) => {
        popEls[n].classList.toggle("live", ct >= o.start_in_output && ct < o.start_in_output + o.duration);
      });
    });
    // pause others when one plays
    video.addEventListener("play", () => document.querySelectorAll("video").forEach((v) => v !== video && v.pause()));
    return el;
  }

  async function tryIt() {
    let health;
    try { health = await (await fetch("api/health", { cache: "no-store" })).json(); } catch { return; }
    if (!health?.ok) return;
    const sec = document.getElementById("try");
    sec.hidden = false;
    document.getElementById("try-limits").textContent = `${health.min_seconds}–${health.max_seconds} s`;
    document.getElementById("try-mb").textContent = health.max_mb;
    document.getElementById("try-ret").textContent = health.retention_min;
    document.getElementById("try-brain").textContent = health.brain === "api" ? "Claude (capped)" : "offline rules";

    const drop = document.getElementById("drop"), input = document.getElementById("file");
    const idle = drop.querySelector(".drop-idle"), busy = drop.querySelector(".drop-busy");
    const err = document.getElementById("drop-err"), note = document.getElementById("busy-note");
    const result = document.getElementById("try-result");
    let running = false;

    drop.addEventListener("click", () => !running && input.click());
    drop.addEventListener("dragover", (e) => { e.preventDefault(); if (!running) drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); if (!running && e.dataTransfer.files[0]) submit(e.dataTransfer.files[0]); });
    input.addEventListener("change", () => input.files[0] && submit(input.files[0]));

    function setStage(stage) {
      const order = [...busy.querySelectorAll("[data-stage]")].map((li) => li.dataset.stage);
      const k = order.indexOf(stage);
      busy.querySelectorAll("[data-stage]").forEach((li, n) => {
        li.classList.toggle("done", n < k);
        li.classList.toggle("live", n === k);
      });
    }

    async function submit(file) {
      running = true; err.hidden = true; result.innerHTML = "";
      idle.hidden = true; busy.hidden = false; drop.classList.add("busy");
      note.textContent = `Uploading ${(file.size / 1048576).toFixed(1)} MB…`;
      setStage("queued");
      try {
        const fd = new FormData(); fd.append("file", file, file.name);
        const r = await fetch("api/try", { method: "POST", body: fd });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || r.statusText);
        note.textContent = `${j.raw_duration_s}s clip accepted. This takes roughly one to two minutes on a shared CPU.`;
        await poll(j.id);
      } catch (e) {
        err.textContent = e.message; err.hidden = false;
      } finally {
        running = false; idle.hidden = false; busy.hidden = true; drop.classList.remove("busy"); input.value = "";
      }
    }

    async function poll(id) {
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500));
        const r = await fetch(`api/jobs/${id}`, { cache: "no-store" });
        if (!r.ok) throw new Error("job disappeared");
        const j = await r.json();
        if (j.state === "error") throw new Error(j.error || "processing failed");
        setStage(j.stage);
        if (j.state === "queued" && j.position > 1) note.textContent = `Queued — ${j.position - 1} ahead of you.`;
        if (j.state === "done") {
          const base = `api/jobs/${id}/`;
          const [edl, dec] = await Promise.all([fetch(base + "edl.json").then((x) => x.json()), fetch(base + "decision.json").then((x) => x.json())]);
          const bay = buildBay(0, base, edl, dec, "YOU");
          const ex = document.createElement("p"); ex.className = "expiry";
          ex.textContent = `This result and your file are deleted from the server in ${Math.round(j.expires_in_s / 60)} min. Right-click the video to save it.`;
          bay.querySelector(".bay-head").after(ex);
          result.appendChild(bay);
          bay.scrollIntoView({ behavior: "smooth", block: "start" });
          return;
        }
      }
    }
  }

  function countUp(el, target, decimals) {
    const t0 = performance.now(), dur = 900;
    const step = (now) => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = (target * e).toFixed(decimals);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
})();
