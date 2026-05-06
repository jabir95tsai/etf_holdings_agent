# ETF Holdings Daily Tracker

每日自動抓取設定清單中的 ETF（目前為 **00981A / 0050 / 006208**）最新持股，與前一筆可用持股比較，產生變化報告，透過 Gmail 寄送通知，並匯出靜態網站可讀的 JSON。

> ⚠️ 本專案僅為資料整理工具，**不會自動下單**，也**不提供任何投資建議**。所有報告結尾皆附免責聲明。

---

## 1. 專案用途

- 每天台灣時間 **15:00** 自動執行；若尚無新資料，每 30 分鐘重試一次
- 抓取 ETF 最新持股（預設 MoneyDJ → EzMoney → 官方 → TWSE）
- 與資料庫中前一筆可用日期做比較，分類：
  - 新建倉 / 清倉 / 增持 / 減持 / 持平
- 增持 / 減持只看股數變化；股數不變但因股價造成的權重變化會歸為持平
- 報告會抓當日收盤價，估算 `股數變化 × 收盤價` 的變化金額
- 產出 Markdown + CSV 報告
- 透過 Gmail SMTP 寄送報告 / 無新資料通知 / 失敗通知
- 匯出 `site/data/{ETF}/latest.json`，供公開靜態網站使用
- 若設定 `OPENAI_API_KEY`，每日產生 AI 解讀；未設定時使用規則版解讀

---

## 2. 系統架構

```
GitHub Actions (cron 0 7 * * *  → Taipei 15:00)
       │
       ▼
src/main.py
  ├── scraper.py   ── 三段式 fallback：official → moneydj → twse
  ├── parser.py    ── HTML / JSON → 標準持股 dict
  ├── db.py        ── SQLite 持久化（holdings_daily / run_logs / alerts）
  ├── comparer.py  ── 兩日快照差異分類
  ├── reporter.py  ── Markdown / CSV 產出 + 資料品質檢查
  └── notifier.py  ── Gmail SMTP 通知

scripts/export_site_data.py
  └── SQLite → site/data JSON → site/index.html 讀取
scripts/generate_ai_analysis.py
  └── site/data JSON → ai_analysis 欄位
```

---

## 3. 資料來源

| 來源 | 用途 | 備註 |
|---|---|---|
| 統一投信 (UPAMC) | 主來源 | 環境變數 `UPAMC_URL` 可覆蓋 |
| MoneyDJ ETF 持股頁 | 第一備援 | `MONEYDJ_URL` |
| TWSE ETF 投資組合 | 第二備援 | `TWSE_URL` |

> 預設 URL 會試著抓 00981A 的官方頁面；若官方頁面變動或封鎖請以環境變數覆寫。每次抓取的原始 HTML/JSON 會存到 `data/raw/` 以便事後追查。

---

## 4. 本機執行

```bash
# 安裝相依
python -m venv .venv
. .venv/Scripts/activate           # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env，填入 Gmail App Password 等

# 跑單元測試
pytest -q
# 或使用隔離測試環境
.\scripts\run_tests.ps1

# 正式執行
python -m src.main --etf 00981A
# 測試環境 dry-run（不寫正式 DB、不寄信）
.\scripts\run_agent_test.ps1
# 測試寄信給自己（使用 .env 的 Gmail 憑證，但資料寫到 data/test）
.\scripts\run_agent_test_email.ps1
# 只寄 Gmail SMTP 測試信
.\scripts\run_agent_test_email.ps1 -NotifyOnly

# 其他指令
python -m src.main --etf 00981A --date 2026-04-24    # 指定資料日期
python -m src.main --etf 00981A --dry-run            # 不寫 DB、不寄信
python -m src.main --etf 00981A --notify-test        # 測試 Gmail SMTP
python -m src.main --etf 00981A --force-report       # 強制重新產報告

# 匯出網站資料
python scripts/export_site_data.py --skip-prices
python scripts/generate_ai_analysis.py --force-rule-based

# 本機預覽網站
cd site
python -m http.server 8765
```

測試環境會透過 `ENV_FILE=.env.test` 載入設定，並使用 `data/test/` 底下的 SQLite、raw files、reports。`.env.test` 不包含 Gmail 密碼，預設不會寄信。若要測試實際寄信，使用 `run_agent_test_email.ps1`，它會讀取 `.env` 的 Gmail 憑證，但強制收件人為測試信箱、資料仍寫入 `data/test/`。

---

## 5. 設定 .env

複製 `.env.example` 為 `.env`，填入：

```env
GMAIL_SMTP_HOST=smtp.gmail.com
GMAIL_SMTP_PORT=587
GMAIL_SENDER_EMAIL=your_email@gmail.com
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
GMAIL_RECEIVER_EMAILS=receiver1@gmail.com,receiver2@gmail.com
NOTIFY_ON_NO_UPDATE=true
SOURCE_ORDER=moneydj,ezmoney,official,twse
# 選填：產生 AI 解讀
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.2
```

也可以沿用舊的 `GMAIL_RECEIVER_EMAIL`，同樣支援用逗號或分號分隔多個收件人。

資料來源順序可用 `SOURCE_ORDER` 調整；預設會優先抓 MoneyDJ，若 MoneyDJ 失敗再使用 EzMoney / 官方 / TWSE 後援。若要擴充其他 ETF，可先用 `EZMONEY_FUND_CODE`、`EZMONEY_EXCEL_URL`、`EZMONEY_REFERER_URL`、`UPAMC_URL`、`MONEYDJ_URL`、`TWSE_URL` 覆寫來源。

`.env` 已在 `.gitignore`（請自行確認）— **絕對不要把 App Password commit 進 Git**。

---

## 6. 建立 Gmail App Password

1. 前往 <https://myaccount.google.com/security>
2. 確認帳戶已啟用 **兩步驟驗證 (2-Step Verification)**
3. 進入 <https://myaccount.google.com/apppasswords>
4. 應用程式選 **「Mail」**、裝置選 **「Other」** → 命名為 `etf-holdings-agent`
5. Google 會給 16 碼密碼（範例：`abcd efgh ijkl mnop`）
6. 把空白去掉後填入 `GMAIL_APP_PASSWORD`

> 如果看不到 App Passwords 選項，代表 2FA 沒開或帳戶政策禁止。改用其他 Gmail 帳號或 Google Workspace 設定後再試。

---

## 7. 設定 GitHub Actions Secrets

在 GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**：

| Secret 名稱 | 值 |
|---|---|
| `GMAIL_SENDER_EMAIL` | 寄件 Gmail（例：`me@gmail.com`） |
| `GMAIL_APP_PASSWORD` | 16 碼 App Password |
| `GMAIL_RECEIVER_EMAILS` | 收件信箱，可用逗號分隔多個帳號 |
| `OPENAI_API_KEY` | 選填；若提供，GitHub Actions 會產生 OpenAI 版 AI 解讀 |

若你已經有舊的 `GMAIL_RECEIVER_EMAIL` Secret，也可以直接把它的值改成 `first@gmail.com,second@gmail.com`，程式仍會讀取。

---

## 8. 啟用每日 15:00 自動執行

`.github/workflows/daily.yml` 已包含：

```yaml
on:
  schedule:
    - cron: '0 7 * * *'     # UTC 07:00 = 台北 15:00
  workflow_dispatch: {}
```

push 到 GitHub `main` branch 後，排程就會生效。**第一次也建議手動觸發** workflow_dispatch 一次以驗證 Secrets 是否正確。workflow 會用 matrix 分別跑 00981A、0050、006208，並使用各自獨立的 GitHub cache 保存 SQLite。

> GitHub-hosted runner 的 cron 並非毫秒精準；通常會在排定時間後 0–15 分鐘內觸發，這是 GitHub 平台行為，不是程式 bug。

---

## 9. 查看 reports

- 報告會寫到 `data/reports/`：
  - `00981A_diff_YYYY-MM-DD.md`
  - `00981A_diff_YYYY-MM-DD.csv`
- GitHub Actions 每次執行也會把 `data/reports/` 與 `data/etf_holdings.sqlite` 上傳成 **artifact**（保留 30 天，可在 Actions run 頁面下載）

---

## 10. 公開網站

靜態網站位於 `site/`：

- `site/index.html`：公開 dashboard
- `site/assets/`：CSS / JS
- `site/data/manifest.json`：ETF 清單
- `site/data/{ETF}/latest.json`：各 ETF 最新報告資料

GitHub Actions 會在每日抓取後匯出 JSON，產生 `ai_analysis`，再將 `site/data` commit 回 repo。部署到 Vercel 時可直接把 `site/` 設為靜態輸出目錄。

目前網站包含本機收藏功能（使用瀏覽器 localStorage）。若要啟用登入與雲端收藏，建立 Supabase 專案後把 public URL / anon key 填入 `site/config.js`：

```js
window.ETF_APP_CONFIG = {
  supabaseUrl: "https://YOUR_PROJECT.supabase.co",
  supabaseAnonKey: "YOUR_PUBLIC_ANON_KEY",
};
```

Supabase SQL：

```sql
create table public.favorite_etfs (
  user_id uuid not null references auth.users(id) on delete cascade,
  etf_code text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, etf_code)
);

alter table public.favorite_etfs enable row level security;

create policy "Users can read own favorite ETFs"
on public.favorite_etfs for select
to authenticated
using (auth.uid() = user_id);

create policy "Users can insert own favorite ETFs"
on public.favorite_etfs for insert
to authenticated
with check (auth.uid() = user_id);

create policy "Users can delete own favorite ETFs"
on public.favorite_etfs for delete
to authenticated
using (auth.uid() = user_id);
```

部署方式：

- **GitHub Pages**：repo 內已提供 `.github/workflows/site.yml`。在 GitHub repo → Settings → Pages 將 Source 設為 **GitHub Actions** 後，push 到 `main` 會自動部署 `site/`。
- **Vercel**：repo 內的 `vercel.json` 已設定 `site/` 為輸出目錄，不需要 build command。

每日資料 workflow 更新 `site/data` 後，也會直接重新部署 GitHub Pages。

---

## 11. 查看 SQLite 資料

```bash
# 內建
sqlite3 data/etf_holdings.sqlite "SELECT date, COUNT(*) FROM holdings_daily GROUP BY date ORDER BY date DESC LIMIT 5;"
sqlite3 data/etf_holdings.sqlite "SELECT * FROM run_logs ORDER BY run_at DESC LIMIT 10;"
sqlite3 data/etf_holdings.sqlite "SELECT * FROM alerts ORDER BY created_at DESC LIMIT 20;"
```

或用 [DB Browser for SQLite](https://sqlitebrowser.org/) 圖形化查看。

---

## 12. 常見錯誤排查

| 症狀 | 可能原因 | 解法 |
|---|---|---|
| `Gmail not configured` warning | `.env` / Secrets 缺欄位 | 補 `GMAIL_SENDER_EMAIL` / `GMAIL_APP_PASSWORD` / `GMAIL_RECEIVER_EMAILS` |
| `smtplib.SMTPAuthenticationError` | App Password 錯誤或帳號未開 2FA | 重新產生 App Password；確認 2FA |
| 「尚無新資料」連續多天 | 官方頁面結構變動或當前為連假 | 看 `data/raw/` 最新 HTML，必要時更新 parser 或 URL |
| `All data sources failed` | 三個來源都抓不到 | 檢查 GitHub Actions runner 的網路是否能訪問來源；或暫時改本機跑驗證 |
| 持股檔數 0 | parser 對該頁面的表頭判讀失敗 | 把 `data/raw/` 內 HTML 複製到 `tests/` 寫一個新的 parser test，再修 `_HOLDINGS_HEADER_HINTS` / `_map_columns` |
| 權重總和顯示 0% | 該來源的「比例」欄位以非 % 數字呈現 | 在 parser 加單位轉換；或更換主來源 |

---

## 13. 免責聲明

**本工具僅作為個人資料整理用途，不構成任何投資建議。** 抓取資料的時效性、正確性、完整性受外部資料源限制，使用者應自行驗證並承擔投資決策的全部責任。本專案不會、也絕不應該被用來自動下單或執行任何金融交易。

---

## 後續可擴充功能（roadmap）

- [x] 支援多檔 ETF matrix（00981A、0050、006208）
- [x] 匯出靜態網站 JSON
- [ ] 部署公開 dashboard
- [ ] Supabase Auth 登入與雲端收藏 ETF
- [ ] 每日 AI 分析摘要
- [x] AI 分析 JSON 欄位與網站區塊（未設定 key 時用規則版）
- [ ] 加入週/月變化彙整報告
- [ ] 把 `alerts` 表改寫成 RSS 或 Slack 通知
- [ ] 加入 Playwright fallback（若官方頁面改為 SPA）
