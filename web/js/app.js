/**
 * IPSC2-MONITOR dashboard client.
 * Copyright (C) 2026 Shane Daley, M0VUB <shane@freestar.network>
 */
(function () {
  const main = document.getElementById("mainpage");
  const titleEl = document.getElementById("site-title");
  const footerEl = document.getElementById("footer-line");
  const themeBtn = document.getElementById("theme-toggle");
  const navLinks = Array.from(document.querySelectorAll("#map a[data-page]"));

  const PAGES = {
    status: "status",
    monitor: "monitor",
    matrix: "matrix",
    remap: "remap",
    bridge: "bridge",
    dongle: "dongle",
    service: "service",
    siteinfo: "site",
  };

  let page = "status";
  let fetchGen = 0;
  let site = { title: "System X", theme: "de" };
  let interacting = false;
  let pendingHtml = null;
  let lastApplied = "";
  let idleTimer = 0;

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function cls(state) {
    if (state === "tx") return " class=\"cell-tx\"";
    if (state === "rx") return " class=\"cell-rx\"";
    if (state === "tx-hang") return " class=\"cell-tx-hang\"";
    if (state === "rx-hang") return " class=\"cell-rx-hang\"";
    if (state === "lock") return " class=\"cell-lock\"";
    return "";
  }

  function lines(value) {
    return esc(value).replace(/\n/g, "<br>");
  }

  function applyTheme(theme) {
    const next = theme === "uk" ? "uk" : "de";
    document.documentElement.setAttribute("data-theme", next);
    themeBtn.textContent = next.toUpperCase();
    localStorage.setItem("ipsc2-dash-theme", next);
  }

  function setNav() {
    navLinks.forEach((link) => {
      link.classList.toggle("active", link.dataset.page === page);
    });
  }

  function wrapTables(root) {
    root.querySelectorAll("table").forEach((table) => {
      if (table.parentElement && table.parentElement.classList.contains("table-scroll")) {
        return;
      }
      const wrap = document.createElement("div");
      wrap.className = "table-scroll";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  }

  function emptyRows(cols, count) {
    let html = "";
    for (let i = 0; i < count; i += 1) {
      html += "<tr>" + "<td>&nbsp;</td>".repeat(cols) + "</tr>";
    }
    return html;
  }

  function renderStatus(data) {
    const banner = `REGISTERED (${esc(data.version || "System X")}) ${esc(data.stamp || "")}`;
    let html = `<table>
      <colgroup>
        <col width="4%"><col width="22%"><col width="15%"><col width="22%"><col width="15%"><col width="22%">
      </colgroup>
      <thead><tr><th colspan="6">${banner}</th></tr></thead>
      <tbody>
        <tr>
          <th class="tableft">NR</th>
          <th class="tableft">REFLECTOR</th>
          <th class="tableft">CALL TS1</th>
          <th>NET TS1</th>
          <th class="tableft">CALL TS2</th>
          <th>NET TS2</th>
        </tr>`;
    const registered = data.registered || [];
    registered.forEach((row, idx) => {
      html += `<tr>
        <td>${idx + 1}</td>
        <td${cls(row.state)}>${esc(row.reflector)}${row.name ? " " + esc(row.name) : ""}</td>
        <td${cls(row.call_ts1 ? row.state : "")}>${esc(row.call_ts1)}</td>
        <td>${esc(row.net_ts1)}</td>
        <td${cls(row.call_ts2 ? row.state : "")}>${esc(row.call_ts2)}</td>
        <td>${esc(row.net_ts2)}</td>
      </tr>`;
    });
    html += emptyRows(6, Math.max(0, 5 - registered.length));
    html += `</tbody></table>
      <div class="ww-cq">WW-CQ active talkgroups: ${
        (data.ww_cq || []).length
          ? (data.ww_cq || []).map((tg) => `<span class="cell-rx">${esc(tg)}</span>`).join(" ")
          : "&lt;"
      }</div>
      <table>
        <colgroup>
          <col width="3%"><col width="7%"><col width="13%"><col width="5%"><col width="10%">
          <col width="3%"><col width="16%"><col width="10%"><col width="16%">
          <col width="5%"><col width="5%"><col width="7%">
        </colgroup>
        <thead><tr><th colspan="12">LINK-STATUS</th></tr></thead>
        <tbody>
          <tr>
            <th class="tableft">NR</th>
            <th class="tableft">REPEATER</th>
            <th class="tableft">INFO</th>
            <th class="tableft">ID</th>
            <th class="tableft">TS1</th>
            <th class="tableft">CQ</th>
            <th>TS1-INFO</th>
            <th class="tableft">TS2</th>
            <th>TS2-INFO</th>
            <th class="tableft">REF</th>
            <th class="tableft">START</th>
            <th class="tableft">HARDWARE</th>
          </tr>`;
    (data.links || []).forEach((row, idx) => {
      html += `<tr>
        <td>${idx + 1}</td>
        <td>${esc(row.repeater)}</td>
        <td>${esc(row.info)}</td>
        <td>${esc(row.id)}</td>
        <td>${esc(row.ts1)}</td>
        <td>${esc(row.cq)}</td>
        <td${cls(row.ts1_info ? row.ts1_state : "")}>${lines(row.ts1_info)}</td>
        <td>${esc(row.ts2)}</td>
        <td${cls(row.ts2_info ? row.ts2_state : "")}>${lines(row.ts2_info)}</td>
        <td>${esc(row.ref)}</td>
        <td>${esc(row.start)}</td>
        <td>${esc(row.hardware)}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    return html;
  }

  function renderMonitor(data) {
    const banner = `REGISTERED (${esc(data.version || "System X")}) ${esc(data.stamp || "")}`;
    let html = `<table>
      <colgroup>
        <col width="5%"><col width="5%"><col width="10%"><col width="5%"><col width="6%">
        <col width="6%"><col width="8%"><col width="11%"><col width="14%">
        <col width="5%"><col width="7%"><col width="5%"><col width="5%"><col width="8%">
      </colgroup>
      <thead><tr><th colspan="14">${banner}</th></tr></thead>
      <tbody>
        <tr>
          <th class="tableft">NR</th><th class="tableft">HW</th><th class="tableft">TIME</th>
          <th class="tableft">SEC</th><th class="tableft">RPTR</th><th class="tableft">CALL</th>
          <th class="tableft">ID</th><th class="tableft">CALL</th><th class="tableft">ALIAS</th>
          <th class="tableft">TS</th><th class="tableft">TG</th><th class="tableft">BER%</th>
          <th class="tableft">RSSI</th><th class="tableft">FLOOR</th>
        </tr>`;
    (data.rows || []).forEach((row) => {
      html += `<tr>
        <td>${esc(row.nr)}</td><td>${esc(row.hw)}</td><td>${esc(row.time)}</td>
        <td>${esc(row.sec)}</td><td>${esc(row.rptr)}</td><td>${esc(row.rptr_call)}</td>
        <td>${esc(row.id)}</td><td>${esc(row.call)}</td><td>${esc(row.alias)}</td>
        <td>${esc(row.ts)}</td><td>${esc(row.tg)}</td><td>${esc(row.ber)}</td>
        <td>${esc(row.rssi)}</td><td>${esc(row.floor)}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    return html;
  }

  function renderMatrixGrid(title, grid) {
    const tgs = (grid && grid.tgs) || [];
    let html = `<table>
      <thead><tr><th colspan="${3 + tgs.length}">${esc(title)}</th></tr></thead>
      <tbody>
        <tr>
          <th class="tableft">RPTR</th>
          <th class="tableft">ID</th>
          <th class="tableft">INFO</th>`;
    tgs.forEach((tg) => {
      html += `<th>${esc(tg)}</th>`;
    });
    html += "</tr>";
    ((grid && grid.rows) || []).forEach((row) => {
      const marks = row.marks || [];
      html += `<tr>
        <td>${esc(row.rptr)}</td>
        <td>${esc(row.id)}</td>
        <td>${esc(row.info)}</td>`;
      tgs.forEach((tg) => {
        html += `<td class="matrix-x">${marks.indexOf(tg) >= 0 ? "X" : ""}</td>`;
      });
      html += "</tr>";
    });
    html += "</tbody></table><br>";
    return html;
  }

  function renderMatrix(data) {
    return renderMatrixGrid("MATRIX TS1", data.ts1) + renderMatrixGrid("MATRIX TS2", data.ts2);
  }

  function renderRemap(data) {
    let html = `<table>
      <thead><tr><th colspan="8">REFLECTOR TO TG MAPPING</th></tr></thead>
      <tbody>
        <tr>
          <th class="tableft">NR</th><th class="tableft">NAME</th><th class="tableft">TG</th>
          <th class="tableft">TS</th><th class="tableft">Reflector</th>
          <th>IDs</th><th>IDs</th><th>ON/OFF</th>
        </tr>`;
    (data.rows || []).forEach((row, idx) => {
      html += `<tr>
        <td>${idx + 1}</td><td>${esc(row.name)}</td><td>${esc(row.tg)}</td>
        <td>${esc(row.ts)}</td><td>${esc(row.reflector)}</td>
        <td>${esc(row.on)}</td><td>${esc(row.off)}</td><td>${esc(row.active)}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    return html;
  }

  function renderBridge(data) {
    let html = `<table>
      <thead><tr><th colspan="6">Bridged talkgroups via -&gt; see TYPE</th></tr></thead>
      <tbody>
        <tr>
          <th class="tableft">NR</th><th class="tableft">TG</th><th class="tableft">INFO</th>
          <th class="tableft">TS</th><th class="tableft">TYPE</th><th class="tableft">ACTIVE</th>
        </tr>`;
    (data.rows || []).forEach((row, idx) => {
      html += `<tr>
        <td>${idx + 1}</td><td>${esc(row.tg)}</td><td>${esc(row.info)}</td>
        <td>${esc(row.ts)}</td><td>${esc(row.type)}</td><td>${esc(row.active)}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    return html;
  }

  function renderDongle(data) {
    let html = `<table>
      <thead><tr><th colspan="6">LINKED APPS</th></tr></thead>
      <tbody>
        <tr>
          <th class="tableft">NR.</th><th class="tableft">DONGLE CALL</th>
          <th class="tableft">PROT</th><th class="tableft">REF / TS1</th>
          <th class="tableft">ID</th><th class="tableft">SV</th>
        </tr>`;
    (data.rows || []).forEach((row, idx) => {
      html += `<tr>
        <td>${idx + 1}</td>
        <td${cls(row.ts1_state || row.ts2_state)}>${esc(row.call)}</td>
        <td>${esc(row.prot)}</td>
        <td>${esc(row.ref)}</td>
        <td>${esc(row.id)}</td>
        <td>${esc(row.sv)}</td>
      </tr>`;
    });
    html += "</tbody></table>";
    return html;
  }

  function renderService(data) {
    const banner = `CONFIG-PAGE REGISTERED (${esc(data.version || "System X")}) ${esc(data.stamp || "")} SYSOP-Email:${esc(data.email || "")}`;
    let html = `<table>
      <thead><tr><th colspan="29">${banner}</th></tr></thead>
      <tbody>
        <tr>
          <th>#</th><th>CONFIG</th><th>HARD<br>WARE</th><th>RPTR</th><th>CALL</th><th>QRG</th><th>SLOT</th>
          <th>1</th><th>2</th><th>3</th><th>4</th><th>5</th><th>6</th><th>7</th><th>8</th><th>9</th>
          <th>1</th><th>2</th><th>3</th><th>4</th><th>5</th><th>6</th><th>7</th><th>8</th><th>9</th>
          <th>REFL</th><th>MIN</th><th>FIRM<br>WARE</th><th>SER #</th>
        </tr>`;
    (data.rows || []).forEach((row, idx) => {
      const ts1 = row.ts1 || [];
      const ts2 = row.ts2 || [];
      html += `<tr>
        <td>${idx + 1}</td><td>${esc(row.config)}</td><td>${esc(row.hardware)}</td>
        <td>${esc(row.rptr)}</td><td>${esc(row.call)}</td><td>${esc(row.qrg)}</td>
        <td>${esc(row.slot)}</td>`;
      for (let i = 0; i < 9; i += 1) html += `<td>${esc(ts1[i] || "0")}</td>`;
      for (let i = 0; i < 9; i += 1) html += `<td>${esc(ts2[i] || "0")}</td>`;
      html += `<td>${esc(row.refl)}</td><td>${esc(row.min)}</td>
        <td>${esc(row.firm)}</td><td>${esc(row.ser)}</td></tr>`;
    });
    html += "</tbody></table>";
    return html;
  }

  function renderSite(data) {
    const lines = [
      "This is a private website.",
      "It shows the status and statistical information of this System X / RYSEN master.",
      "The server is part of the worldwide Amateur Radio DMR digital voice network, which connects Amateur Radio repeaters and hotspots together.",
      "Users with a valid Amateur Radio license may connect their Repeaters and Dongles freely and use it within the local and international Amateur Radio regulations.",
      "Connects from non Amateur Radio stations is strictly prohibited.",
      "Public repeaters with a license for 24/7 unattended use need to be registered at the DMR-ID Registration system.",
      "Private repeaters should be configured with the registered DMR-ID of the owner.",
      "Please note that on Amateur Radio identification with the callsign is required. In DMR the registered DMR-ID is used instead. Both information are shown on the status pages.",
      "In case that you do not want your repeater and your users to be visible, disconnect from the network please.",
      "Our network policy does not allow anonymous usage of the system.",
      "These data are shared with other network components worldwide for access control, identification, routing and reflector system functionality.",
      `Version: ${data.version || "—"}   Linked peers: ${data.peer_count || 0}   Bridges: ${data.bridge_count || 0}   Report: ${data.connected ? "online" : "offline"}`,
      "Contact:",
      data.contact_name || "",
      data.contact_country || "",
      data.contact_email ? `email: ${data.contact_email}` : "",
    ];
    let html = `<table class="site-copy">
      <thead><tr><th colspan="2">SITE-INFO</th></tr></thead><tbody>`;
    lines.forEach((line) => {
      html += `<tr><td></td><td>${esc(line)}</td></tr>`;
    });
    html += "</tbody></table>";
    return html;
  }

  const RENDERERS = {
    status: renderStatus,
    monitor: renderMonitor,
    matrix: renderMatrix,
    remap: renderRemap,
    bridge: renderBridge,
    dongle: renderDongle,
    service: renderService,
    site: renderSite,
  };

  async function fetchJson(path) {
    const resp = await fetch(path, { cache: "no-store" });
    if (!resp.ok) throw new Error(resp.statusText);
    return resp.json();
  }

  function captureScroll() {
    return {
      mainTop: main.scrollTop,
      mainLeft: main.scrollLeft,
      winY: window.scrollY,
      winX: window.scrollX,
      tables: Array.from(main.querySelectorAll(".table-scroll")).map((el) => ({
        top: el.scrollTop,
        left: el.scrollLeft,
      })),
    };
  }

  function restoreScroll(saved) {
    main.scrollTop = saved.mainTop;
    main.scrollLeft = saved.mainLeft;
    window.scrollTo(saved.winX, saved.winY);
    const wraps = main.querySelectorAll(".table-scroll");
    saved.tables.forEach((pos, idx) => {
      if (!wraps[idx]) return;
      wraps[idx].scrollTop = pos.top;
      wraps[idx].scrollLeft = pos.left;
    });
  }

  function applyHtml(html) {
    if (html === lastApplied) return;
    const saved = captureScroll();
    main.innerHTML = html;
    if (!html.startsWith("<p class=\"empty-note\"")) {
      wrapTables(main);
    }
    lastApplied = html;
    restoreScroll(saved);
  }

  function markBusy() {
    interacting = true;
    window.clearTimeout(idleTimer);
    idleTimer = window.setTimeout(() => {
      interacting = false;
      if (pendingHtml != null) {
        applyHtml(pendingHtml);
        pendingHtml = null;
      }
    }, 800);
  }

  function paint(html) {
    if (interacting) {
      pendingHtml = html;
      return;
    }
    applyHtml(html);
  }

  async function refresh() {
    const endpoint = PAGES[page] || "status";
    const gen = ++fetchGen;
    try {
      const data = await fetchJson("api/" + endpoint);
      if (gen !== fetchGen) return;
      paint(RENDERERS[endpoint](data));
    } catch (err) {
      if (gen !== fetchGen) return;
      paint(`<p class="empty-note">Waiting for dashboard data (${esc(err.message)}).</p>`);
    }
  }

  async function loadSite() {
    try {
      site = await fetchJson("api/site");
      titleEl.textContent = site.title || "System X";
      document.title = (site.title || "System X") + " Dashboard";
      footerEl.textContent = (site.title || "System X") + (site.version ? "  " + site.version : "");
      if (!localStorage.getItem("ipsc2-dash-theme") && site.theme) {
        applyTheme(site.theme);
      }
    } catch (err) {
      /* keep defaults until the sidecar is up */
    }
  }

  function showPage(name) {
    const next = PAGES[name] ? name : "status";
    page = next;
    interacting = false;
    pendingHtml = null;
    lastApplied = "";
    setNav();
    refresh();
    const hash = "#" + next;
    if (location.hash !== hash) {
      location.hash = hash;
    }
  }

  navLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      showPage(link.dataset.page);
    });
  });

  window.addEventListener("hashchange", () => {
    const name = location.hash.replace("#", "") || "status";
    if (name !== page) {
      showPage(name);
    }
  });

  themeBtn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    applyTheme(current === "uk" ? "de" : "uk");
  });

  ["touchstart", "touchmove", "pointerdown", "wheel"].forEach((type) => {
    document.addEventListener(type, markBusy, { passive: true });
  });
  document.addEventListener("scroll", markBusy, { passive: true, capture: true });

  applyTheme(localStorage.getItem("ipsc2-dash-theme") || "de");
  showPage(location.hash.replace("#", "") || "status");
  loadSite();
  setInterval(refresh, 1000);
  setInterval(loadSite, 5000);
}());
