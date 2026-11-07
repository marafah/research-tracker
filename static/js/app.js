/* Research Tracker — UI behaviour (vanilla JS + Bootstrap 5).
   Sidebar collapse · Ctrl/⌘+K command palette · count-up numbers · reveal-on-scroll · animated charts. */
(function () {
  "use strict";
  const html = document.documentElement;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- Sidebar collapse (remembered) ---- */
  document.getElementById("sb-toggle")?.addEventListener("click", () => {
    html.classList.toggle("sb-mini");
    try { localStorage.setItem("rt-sb", html.classList.contains("sb-mini") ? "mini" : "full"); } catch (e) {}
  });
  document.querySelectorAll(".sb-link").forEach(a => {
    const label = a.querySelector(".sb-label");
    if (label) a.setAttribute("data-tip", label.textContent.trim());
  });

  /* ---- Command palette ---- */
  const palEl = document.getElementById("palette");
  if (palEl && window.bootstrap) {
    const modal = bootstrap.Modal.getOrCreateInstance(palEl);
    const input = document.getElementById("palette-input");
    const list = document.getElementById("palette-list");
    const searchLink = list.querySelector(".palette-search-link");
    let idx = 0;
    const items = () => [...list.querySelectorAll("a")].filter(a => a.style.display !== "none");
    const mark = () => items().forEach((a, i) => a.classList.toggle("on", i === idx));
    const filter = () => {
      const q = input.value.trim().toLowerCase();
      list.querySelectorAll("a").forEach(a => {
        if (a === searchLink) { a.style.display = q ? "" : "none"; a.querySelector("b").textContent = input.value.trim(); return; }
        a.style.display = !q || a.textContent.toLowerCase().includes(q) ? "" : "none";
      });
      list.querySelectorAll(".palette-group").forEach(g => g.style.display = q ? "none" : "");
      idx = 0; mark();
    };
    const open = () => { modal.show(); };
    palEl.addEventListener("show.bs.modal", () => { input.value = ""; filter(); });
    palEl.addEventListener("shown.bs.modal", () => input.focus());
    document.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); open(); }
    });
    document.querySelectorAll("[data-palette]").forEach(b => b.addEventListener("click", open));
    input.addEventListener("input", filter);
    input.addEventListener("keydown", e => {
      const it = items();
      if (e.key === "ArrowDown") { idx = Math.min(idx + 1, it.length - 1); mark(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { idx = Math.max(idx - 1, 0); mark(); e.preventDefault(); }
      else if (e.key === "Enter") {
        e.preventDefault();
        const q = input.value.trim();
        const target = it[idx];
        if (target === searchLink || (!target && q)) location.href = searchLink.dataset.searchUrl + encodeURIComponent(q);
        else if (target) location.href = target.href;
      }
    });
    searchLink.addEventListener("click", e => {
      e.preventDefault(); location.href = searchLink.dataset.searchUrl + encodeURIComponent(input.value.trim());
    });
  }

  /* ---- Count-up numbers ---- */
  const countUp = el => {
    const raw = el.textContent.trim();
    const m = raw.match(/^(\d+)(.*)$/);
    if (!m || reduce) return;
    const end = +m[1], suffix = m[2], t0 = performance.now(), dur = 700;
    if (end === 0) return;
    const step = t => {
      const p = Math.min(1, (t - t0) / dur), v = Math.round(end * (1 - Math.pow(1 - p, 3)));
      el.textContent = v + suffix;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  document.querySelectorAll(".stat .s-value, .ws-kpi b, .donut2 b, .donut b, [data-count]").forEach(el => {
    if (el.childNodes.length === 1 && el.firstChild.nodeType === 3) countUp(el);
  });

  /* ---- Reveal on scroll ---- */
  if (!reduce && "IntersectionObserver" in window) {
    const targets = document.querySelectorAll(".content .card, .content .stat, .content .ws-kpi, .rec-card, .vt-item, .board-col, .mini-paper, .qa");
    const io = new IntersectionObserver(entries => entries.forEach(en => {
      if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
    }), { rootMargin: "0px 0px -40px 0px" });
    targets.forEach((el, i) => { el.classList.add("reveal"); el.style.setProperty("--d", Math.min(i, 12) * 35 + "ms"); io.observe(el); });
    setTimeout(() => targets.forEach(el => el.classList.add("in")), 600); /* safety net (print, screenshots) */
  }

  /* ---- Animated charts (bars grow, donuts sweep) ---- */
  if (!reduce) {
    document.querySelectorAll(".bar-stack span, .tr-bar span, .s-bar span, .progress-bar, .stackbar span").forEach(b => {
      const prop = b.closest(".bar-stack") ? "height" : "width";
      const target = b.style[prop];
      if (!target) return;
      b.style[prop] = "0";
      b.style.transition = prop + " .9s cubic-bezier(.2,.8,.2,1)";
      requestAnimationFrame(() => requestAnimationFrame(() => { b.style[prop] = target; }));
    });
    document.querySelectorAll(".donut2[data-stops]").forEach(d => {
      const stops = d.dataset.stops, t0 = performance.now(), dur = 900;
      const step = t => {
        const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
        d.style.background = `conic-gradient(${stops}), var(--rt-surface-2)`;
        d.style.webkitMaskImage = d.style.maskImage = `conic-gradient(#000 ${e * 360}deg, transparent 0)`;
        if (p < 1) requestAnimationFrame(step); else d.style.webkitMaskImage = d.style.maskImage = "";
      };
      requestAnimationFrame(step);
    });
  }

  /* ---- Tooltips for collapsed sidebar ---- */
  if (window.bootstrap) {
    document.querySelectorAll(".sb-link[data-tip]").forEach(a => new bootstrap.Tooltip(a, {
      title: a.dataset.tip, placement: html.dir === "rtl" ? "left" : "right", trigger: "hover",
      customClass: "sb-tip"
    }));
  }
})();

/* Topbar border once the page scrolls */
(function () {
  const tb = document.querySelector(".topbar");
  if (!tb) return;
  const on = () => tb.classList.toggle("scrolled", scrollY > 4);
  addEventListener("scroll", on, { passive: true }); on();
})();

/* Show / hide password */
document.addEventListener("click", e => {
  const b = e.target.closest("[data-toggle-pw]"); if (!b) return;
  const inp = document.querySelector(b.dataset.togglePw); if (!inp) return;
  const show = inp.type === "password"; inp.type = show ? "text" : "password";
  b.querySelector("i").className = show ? "bi bi-eye-slash" : "bi bi-eye";
});
