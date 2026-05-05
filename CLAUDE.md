# CLAUDE.md — ETF Holdings Agent

## 專案用途

每日自動追蹤 **00981A** 持股變化，與前一筆 DB snapshot 比較，寄 Gmail 報告。不自動下單，不提供投資建議。

## 架構

```
src/main.py          # 主流程：scrape → store → diff → report → notify
src/config.py        # dotenv 載入，AppConfig / GmailConfig dataclass
src/scraper.py       # 四段式 fallback (moneydj → ezmoney → official → twse)
src/parser.py        # HTML/JSON → 標準持股 list[dict]
src/db.py            # SQLite (holdings_daily / run_logs / alerts)
src/comparer.py      # 兩日快照差異分類（新建倉/清倉/增持/減持/持平）
src/prices.py        # 收盤價 enrich（TWSE API）
src/reporter.py      # Markdown / CSV / HTML email render
src/notifier.py      # Gmail SMTP 寄信
```

## 環境設定

| 環境變數 | 用途 |
|---|---|
| `GMAIL_SENDER_EMAIL` | 寄件帳號 |
| `GMAIL_APP_PASSWORD` | 16 碼 App Password |
| `GMAIL_RECEIVER_EMAILS` | 收件人，逗號/分號分隔 |
| `NOTIFY_ON_NO_UPDATE` | 無新資料時也寄信（預設 true） |
| `SOURCE_ORDER` | 來源順序（預設 moneydj,ezmoney,official,twse） |
| `ENV_FILE` | 指定要載入的 .env 路徑（測試用） |

`.env.test` 供測試環境使用，不含 Gmail 密碼。

## 常用指令

```bash
# 啟動虛擬環境
.venv/Scripts/activate

# 跑測試
pytest -q

# 正式執行
python -m src.main --etf 00981A

# dry-run（不寫 DB、不寄信）
python -m src.main --etf 00981A --dry-run

# 測試 Gmail SMTP
python -m src.main --etf 00981A --notify-test

# 指定資料日期
python -m src.main --etf 00981A --date 2026-04-24

# 強制重產報告
python -m src.main --etf 00981A --force-report

# 測試 scripts（隔離環境）
.\scripts\run_tests.ps1
.\scripts\run_agent_test.ps1
.\scripts\run_agent_test_email.ps1
```

## GitHub Actions

- 排程：UTC 07:00 = Taipei 15:00，每天執行
- 最多重試 18 次（間隔 30 分鐘），等新資料出現
- SQLite 透過 `actions/cache` 跨 run 保存
- Secrets：`GMAIL_SENDER_EMAIL`、`GMAIL_APP_PASSWORD`、`GMAIL_RECEIVER_EMAILS`

## 資料路徑

```
data/etf_holdings.sqlite   # 主資料庫（holdings_daily / run_logs / alerts）
data/raw/                  # 每次抓取的原始 HTML/JSON（除錯用）
data/reports/              # Markdown + CSV 報告
data/test/                 # 測試環境資料（ENV_FILE=.env.test 時使用）
```

## 開發慣例

- Python 3.11，依賴在 `requirements.txt`
- 所有 config 走 `load_config()`，不直接讀 `os.getenv` 在業務邏輯裡
- 測試在 `tests/`，有 sample HTML fixtures；新增 parser 支援要一起加 test
- 比較邏輯：增持/減持只看**股數**變化；股價造成的權重浮動歸持平
- Email HTML 由 `reporter.render_email_html()` 產出，inline CSS，支援 mobile

## SQLite 快速查詢

```bash
sqlite3 data/etf_holdings.sqlite "SELECT date, COUNT(*) FROM holdings_daily GROUP BY date ORDER BY date DESC LIMIT 5;"
sqlite3 data/etf_holdings.sqlite "SELECT * FROM run_logs ORDER BY run_at DESC LIMIT 10;"
```
