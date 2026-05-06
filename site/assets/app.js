const state = {
  manifest: null,
  currentEtf: null,
  data: null,
  favorites: new Set(JSON.parse(localStorage.getItem("favoriteEtfs") || "[]")),
  supabase: null,
  user: null,
  remoteFavoritesReady: false,
};

const $ = (id) => document.getElementById(id);

const escapeHtml = (value) =>
  String(value ?? "-")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

const formatInt = (value) => {
  if (value === null || value === undefined) return "-";
  return Number(value).toLocaleString("zh-TW");
};

const formatPct = (value) => {
  if (value === null || value === undefined) return "-";
  return `${Number(value).toFixed(2)}%`;
};

const formatBp = (value) => {
  if (value === null || value === undefined) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(1)} bp`;
};

const compactMoney = (value) => {
  if (value === null || value === undefined) return "-";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const amount = Math.abs(Number(value));
  if (amount >= 100000000) return `${sign}${(amount / 100000000).toFixed(2)} 億`;
  if (amount >= 10000) return `${sign}${Math.round(amount / 10000).toLocaleString("zh-TW")} 萬`;
  return `${sign}${amount.toLocaleString("zh-TW")}`;
};

const signedCount = (value, sign) => {
  const count = Number(value || 0);
  if (count === 0) return "0";
  return `${sign}${count}`;
};

const signedClass = (value) => {
  if (Number(value) > 0) return "up";
  if (Number(value) < 0) return "down";
  return "";
};

async function loadManifest() {
  const response = await fetch(`data/manifest.json?t=${Date.now()}`);
  if (!response.ok) throw new Error("manifest not found");
  state.manifest = await response.json();
  const firstFavorite = state.manifest.etfs.find((etf) => state.favorites.has(etf.code));
  state.currentEtf = firstFavorite?.code || state.manifest.etfs[0]?.code;
}

function hasSupabaseConfig() {
  const config = window.ETF_APP_CONFIG || {};
  return Boolean(config.supabaseUrl && config.supabaseAnonKey && window.supabase);
}

function persistLocalFavorites() {
  localStorage.setItem("favoriteEtfs", JSON.stringify([...state.favorites]));
}

async function initAuth() {
  if (!hasSupabaseConfig()) {
    $("authStatus").textContent = "本機收藏";
    $("authButton").textContent = "登入";
    return;
  }

  const config = window.ETF_APP_CONFIG;
  state.supabase = window.supabase.createClient(
    config.supabaseUrl,
    config.supabaseAnonKey,
  );

  const { data } = await state.supabase.auth.getSession();
  await applySession(data.session);

  state.supabase.auth.onAuthStateChange(async (_event, session) => {
    await applySession(session);
    if (state.manifest) renderTabs();
    updateFavoriteButton();
  });
}

async function applySession(session) {
  state.user = session?.user || null;
  state.remoteFavoritesReady = false;

  if (!state.user) {
    $("authStatus").textContent = "本機收藏";
    $("authButton").textContent = "登入";
    return;
  }

  $("authStatus").textContent = state.user.email || "已登入";
  $("authButton").textContent = "登出";
  await loadRemoteFavorites();
}

async function loadRemoteFavorites() {
  if (!state.supabase || !state.user) return;

  const { data, error } = await state.supabase
    .from("favorite_etfs")
    .select("etf_code")
    .eq("user_id", state.user.id);

  if (error) {
    console.warn("Remote favorites unavailable; using local favorites.", error);
    $("authStatus").textContent = `${state.user.email || "已登入"} · 本機收藏`;
    return;
  }

  state.favorites = new Set((data || []).map((row) => row.etf_code));
  state.remoteFavoritesReady = true;
  persistLocalFavorites();
}

async function handleAuthClick() {
  if (!hasSupabaseConfig()) {
    alert("尚未設定 Supabase，現在會先使用本機收藏。");
    return;
  }

  if (state.user) {
    await state.supabase.auth.signOut();
    return;
  }

  const email = window.prompt("輸入 email，系統會寄出登入連結：");
  if (!email) return;

  const { error } = await state.supabase.auth.signInWithOtp({
    email,
    options: {
      emailRedirectTo: window.location.href,
    },
  });
  if (error) {
    alert(`登入信寄送失敗：${error.message}`);
    return;
  }

  alert("登入連結已寄出，請到信箱收信。");
}

async function loadEtf(code) {
  const entry = state.manifest.etfs.find((etf) => etf.code === code);
  if (!entry) return;
  const response = await fetch(`${entry.path}?t=${Date.now()}`);
  if (!response.ok) throw new Error(`${code} data not found`);
  state.currentEtf = code;
  state.data = await response.json();
  render();
}

function renderTabs() {
  $("etfTabs").innerHTML = state.manifest.etfs
    .map((etf) => {
      const favorite = state.favorites.has(etf.code) ? " ★" : "";
      return `<button class="tab ${etf.code === state.currentEtf ? "active" : ""}" type="button" data-etf="${etf.code}">
        ${escapeHtml(etf.code)}${favorite}
      </button>`;
    })
    .join("");

  document.querySelectorAll("[data-etf]").forEach((button) => {
    button.addEventListener("click", () => loadEtf(button.dataset.etf));
  });
}

function renderHeader() {
  const { etf, dates, source, quality, brief } = state.data;
  $("etfTitle").textContent = `${etf.code} ${etf.name}`;
  $("reportMeta").textContent = `報告日期 ${dates.current || "-"} · 比較 ${dates.previous || "-"}`;
  $("brief").textContent = brief || "目前沒有摘要。";
  $("sourceBadge").textContent = `來源 ${source.source_used || "-"}`;
  $("qualityBadge").className = quality.notes.length ? "badge bad" : "badge good";
  $("qualityBadge").textContent = quality.notes.length ? "需留意" : "資料正常";
  updateFavoriteButton();
}

function renderKpis() {
  const summary = state.data.summary;
  const cards = [
    ["今日持股", summary.current_count, `前次 ${summary.previous_count} 檔`, ""],
    ["新建倉", signedCount(summary.new_count, "+"), "檔新增", "up"],
    ["清倉", signedCount(summary.sold_count, "-"), "檔出清", "down"],
    [
      "增 / 減持",
      `<span class="up">增 ${summary.increased_count}</span> <span class="down">減 ${summary.decreased_count}</span>`,
      "檔異動",
      "",
    ],
  ];

  $("kpis").innerHTML = cards
    .map(([label, value, note, cls]) => `
      <article class="kpi">
        <p>${escapeHtml(label)}</p>
        <strong class="${cls}">${value}</strong>
        <span>${escapeHtml(note)}</span>
      </article>
    `)
    .join("");
}

function renderHighlight(prefix, row) {
  const name = row ? `${row.stock_code || "-"} ${row.stock_name || ""}` : "-";
  const amount = row?.estimated_change_amount_label || compactMoney(row?.estimated_change_amount);
  const meta = row
    ? `股數 ${row.delta_shares_label || formatInt(row.delta_shares)} · 權重 ${formatPct(row.current_weight_pct ?? row.previous_weight_pct)}`
    : "-";
  $(`${prefix}Name`).textContent = name;
  $(`${prefix}Amount`).textContent = amount;
  $(`${prefix}Meta`).textContent = meta;
}

function renderHighlights() {
  renderHighlight("topBuy", state.data.highlights.top_buy);
  renderHighlight("topSell", state.data.highlights.top_sell);
}

function sectionClass(kind) {
  if (kind === "buy") return "buy";
  if (kind === "sell") return "sell";
  return "neutral";
}

function emptyMessage(title) {
  if (title.includes("減持")) return "今日無減持紀錄";
  if (title.includes("增持")) return "今日無增持紀錄";
  if (title.includes("新建")) return "今日無新建倉";
  if (title.includes("清倉")) return "今日無清倉紀錄";
  return "目前無資料";
}

function renderChangeRows(rows, type) {
  return rows
    .map((row) => `
      <tr>
        <td>${escapeHtml(row.stock_code)}</td>
        <td>${escapeHtml(row.stock_name)}</td>
        <td class="num ${signedClass(row.delta_shares)}">${row.delta_shares_label || formatInt(row.delta_shares)}</td>
        <td class="num ${signedClass(row.estimated_change_amount)}">${row.estimated_change_amount_label || compactMoney(row.estimated_change_amount)}</td>
        <td class="num">${formatPct(type === "sold" ? row.previous_weight_pct : row.current_weight_pct)}</td>
        <td class="num ${signedClass(row.delta_weight_bp)}">${formatBp(row.delta_weight_bp)}</td>
      </tr>
    `)
    .join("");
}

function renderChangeCards(rows, type) {
  return rows
    .map((row) => `
      <article class="mobile-card">
        <h4>${escapeHtml(row.stock_code)} ${escapeHtml(row.stock_name)}</h4>
        <dl>
          <div><dt>股數變化</dt><dd class="${signedClass(row.delta_shares)}">${row.delta_shares_label || formatInt(row.delta_shares)}</dd></div>
          <div><dt>估值變化</dt><dd class="${signedClass(row.estimated_change_amount)}">${row.estimated_change_amount_label || compactMoney(row.estimated_change_amount)}</dd></div>
          <div><dt>權重</dt><dd>${formatPct(type === "sold" ? row.previous_weight_pct : row.current_weight_pct)}</dd></div>
          <div><dt>變化</dt><dd class="${signedClass(row.delta_weight_bp)}">${formatBp(row.delta_weight_bp)}</dd></div>
        </dl>
      </article>
    `)
    .join("");
}

function renderChangeSection(title, rows, kind, type = "current") {
  const visibleRows = rows.slice(0, 10);
  if (!visibleRows.length) {
    return `
      <section class="panel">
        <div class="section-title ${sectionClass(kind)}"><h3>${escapeHtml(title)}</h3></div>
        <div class="empty ${kind === "buy" ? "good" : ""}">${escapeHtml(emptyMessage(title))}</div>
      </section>
    `;
  }

  return `
    <section class="panel">
      <div class="section-title ${sectionClass(kind)}"><h3>${escapeHtml(title)}</h3></div>
      <div class="table-wrap desktop-table">
        <table>
          <thead>
            <tr>
              <th>代號</th>
              <th>名稱</th>
              <th class="num">股數</th>
              <th class="num">估值</th>
              <th class="num">權重</th>
              <th class="num">變化</th>
            </tr>
          </thead>
          <tbody>${renderChangeRows(visibleRows, type)}</tbody>
        </table>
      </div>
      <div class="mobile-cards">${renderChangeCards(visibleRows, type)}</div>
    </section>
  `;
}

function rankBadge(row) {
  if (!row.previous_rank) return `<span class="rank-badge up">NEW</span>`;
  const delta = row.previous_rank - row.current_rank;
  if (delta > 0) return `<span class="rank-badge up">▲${delta}</span>`;
  if (delta < 0) return `<span class="rank-badge down">▼${Math.abs(delta)}</span>`;
  return `<span class="rank-badge">-</span>`;
}

function renderTopHoldings(rows) {
  const body = rows
    .map((row) => `
      <tr>
        <td class="num">${escapeHtml(row.current_rank)}</td>
        <td>${rankBadge(row)}</td>
        <td>${escapeHtml(row.stock_code)}</td>
        <td>${escapeHtml(row.stock_name)}</td>
        <td class="num">${formatPct(row.current_weight_pct)}</td>
        <td class="num">${formatPct(row.previous_weight_pct)}</td>
        <td class="num ${signedClass(row.delta_weight_bp)}">${formatBp(row.delta_weight_bp)}</td>
      </tr>
    `)
    .join("");

  const cards = rows
    .map((row) => `
      <article class="mobile-card">
        <h4>${escapeHtml(row.current_rank)}. ${escapeHtml(row.stock_code)} ${escapeHtml(row.stock_name)} ${rankBadge(row)}</h4>
        <dl>
          <div><dt>今日權重</dt><dd>${formatPct(row.current_weight_pct)}</dd></div>
          <div><dt>前次權重</dt><dd>${formatPct(row.previous_weight_pct)}</dd></div>
          <div><dt>變化</dt><dd class="${signedClass(row.delta_weight_bp)}">${formatBp(row.delta_weight_bp)}</dd></div>
          <div><dt>前次排名</dt><dd>${escapeHtml(row.previous_rank)}</dd></div>
        </dl>
      </article>
    `)
    .join("");

  return `
    <section class="panel">
      <div class="section-title neutral"><h3>前十大持股</h3></div>
      <div class="table-wrap desktop-table">
        <table>
          <thead>
            <tr>
              <th class="num">排名</th>
              <th>變動</th>
              <th>代號</th>
              <th>名稱</th>
              <th class="num">今日權重</th>
              <th class="num">前次權重</th>
              <th class="num">變化</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
      <div class="mobile-cards">${cards}</div>
    </section>
  `;
}

function renderSections() {
  const sections = state.data.sections;
  $("sections").innerHTML = [
    renderChangeSection("新建倉", sections.new_positions, "buy"),
    renderChangeSection("清倉", sections.sold_out, "sell", "sold"),
    renderChangeSection("增持 Top 10", sections.increased, "buy"),
    renderChangeSection("減持 Top 10", sections.decreased, "sell"),
    renderTopHoldings(sections.top_holdings || []),
  ].join("");
}

function renderQuality() {
  const quality = state.data.quality;
  const items = [
    ["持股檔數", `${quality.rows_count} 檔`],
    ["權重總和", formatPct(quality.weight_total)],
    ["資料來源", quality.source_used || "-"],
    ["缺漏欄位", `代號 ${quality.missing_codes} / 名稱 ${quality.missing_names}`],
    ["重複股票", `${quality.duplicate_codes}`],
    ["提醒", quality.notes.length ? quality.notes.join("、") : "無"],
  ];

  $("qualityList").innerHTML = items
    .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`)
    .join("");
}

function updateFavoriteButton() {
  const button = $("favoriteButton");
  const active = state.favorites.has(state.currentEtf);
  button.textContent = active ? "★" : "☆";
  button.classList.toggle("active", active);
  button.setAttribute("aria-pressed", String(active));
}

async function toggleFavorite() {
  if (!state.currentEtf) return;
  const nextFavorite = !state.favorites.has(state.currentEtf);

  if (state.favorites.has(state.currentEtf)) {
    state.favorites.delete(state.currentEtf);
  } else {
    state.favorites.add(state.currentEtf);
  }
  persistLocalFavorites();
  renderTabs();
  updateFavoriteButton();

  if (!state.supabase || !state.user || !state.remoteFavoritesReady) return;

  if (nextFavorite) {
    const { error } = await state.supabase.from("favorite_etfs").upsert(
      {
        user_id: state.user.id,
        etf_code: state.currentEtf,
      },
      { onConflict: "user_id,etf_code" },
    );
    if (error) console.warn("Failed to save remote favorite.", error);
  } else {
    const { error } = await state.supabase
      .from("favorite_etfs")
      .delete()
      .eq("user_id", state.user.id)
      .eq("etf_code", state.currentEtf);
    if (error) console.warn("Failed to remove remote favorite.", error);
  }
}

function render() {
  renderTabs();
  renderHeader();
  renderKpis();
  renderHighlights();
  renderSections();
  renderQuality();
}

async function boot() {
  $("favoriteButton").addEventListener("click", toggleFavorite);
  $("authButton").addEventListener("click", handleAuthClick);
  try {
    await initAuth();
    await loadManifest();
    if (!state.currentEtf) throw new Error("no ETF data");
    await loadEtf(state.currentEtf);
  } catch (error) {
    $("brief").textContent = "目前找不到網站資料，請先執行 JSON 匯出。";
    $("reportMeta").textContent = "尚無資料";
    console.error(error);
  }
}

boot();
