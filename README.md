# CH WG Monitor

Monitors Swiss flatshare (WG) portals, evaluates each listing via AI through OpenRouter, and sends matches via Telegram.

Forked from a Kleinanzeigen used-goods monitor; the AI evaluation, Telegram notification, deduplication, config and telemetry are portal-agnostic — only fetching/parsing is per-portal.

## How it works

```
portal search → fetch listings → AI evaluates → Telegram message
```

On each run the script iterates over all configured `[[searches]]`. Each search names a **portal** (adapter) and its filter. Current listings are fetched, and every listing not yet in `seen.json` is sent to a language model via [OpenRouter](https://openrouter.ai), which decides — based on `common_prompt`, `max_price` (CHF) and `addition_prompt` — whether it is a match. On `match: true` a Telegram message is sent.

**Deduplication**: all seen listing IDs are stored in `seen.json`. Listings whose evaluation errored are *not* stored, so they are retried next run.

**deep_eval** (optional, 2-step): a cheap prefilter on title/price, then a detail-page fetch for a thorough second evaluation.

## Portals

| Portal | Status | How it fetches |
|---|---|---|
| **flatfox** | ✅ working | Public JSON API. Uses the map-pin endpoint (`/api/v1/pin/`, server-side filtered by bounding box + `object_category`) to get matching pks, then batch-fetches full listings by pk. Exact box results in ~2 requests. No key, no captcha. |
| **wgzimmer** | ⚠️ stub | Search is gated by reCAPTCHA v3. Captcha solving (via 2Captcha) is implemented, but wgzimmer only renders results above a v3 *score* that datacenter solvers can't reach — it needs a real headless browser. Left in place for a future Playwright fetch path. |
| **kleinanzeigen** | legacy | Original HTML scraper, kept as a reference adapter. |

Portal is chosen per search via `portal = "..."`, or inferred from the URL host.

## Setup

### 1. Telegram bot

1. Open [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name + username ending in `bot`.
2. Copy the **bot token** (`123456789:AAF...`).
3. Message the bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id":...}`.

### 2. API keys

- **OpenRouter**: account at [openrouter.ai](https://openrouter.ai) → API Keys.
- **2Captcha** (only if you enable wgzimmer): key at [2captcha.com](https://2captcha.com).

### 3. Fill in `.env`

```
cp .env.example .env
```

```
OPENROUTER_API_KEY=sk-or-v1-...
TELEGRAM_BOT_TOKEN=123456789:AAF...
TELEGRAM_CHAT_ID=987654321
# CAPTCHA_API_KEY=...        # only for wgzimmer
```

### 4. Configure searches

Edit `config.toml` — one `[[searches]]` block per search. For **flatfox**, build the search on [flatfox.ch](https://flatfox.ch/de/suche/) (draw the map area, set filters) and paste the URL; its `object_category` + `north/south/east/west` bounds are used as the filter.

```toml
[assistant]
common_prompt = "Ich suche ein WG-Zimmer in der Schweiz. Preise sind in CHF pro Monat."
deep_eval = true

[[searches]]
portal = "flatfox"
url = "https://flatfox.ch/de/suche/?object_category=SHARED&north=47.32&south=47.13&east=8.95&west=8.68"
max_price = 1200                    # CHF
addition_prompt = "WG-Zimmer im Umfeld von Rapperswil-Jona, unbefristet, Einzug ab sofort."
# max_count = 400                   # optional: cap on map pins fetched per box
```

### 5. Run

```bash
uv run main.py run                     # normal run
uv run main.py run --dry-run           # evaluate but don't send Telegram
uv run main.py run --test-telegram     # verify Telegram config
uv run pytest tests/ -v                # tests
```

### 6. OpenTelemetry (optional)

Exports traces, metrics and logs via OTLP/HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (no-op otherwise).

```
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-eu-west-2.grafana.net/otlp
OTEL_SERVICE_NAME=ch-wg-monitor
DEPLOYMENT_ENVIRONMENT=production
```

**Exported metrics:**

| Metric | Type | Description |
|---|---|---|
| `monitor.listings.fetched` | Counter | Total listings fetched |
| `monitor.listings.new` | Counter | New listings evaluated |
| `monitor.listings.matched` | Counter | Matched listings sent |
| `monitor.listings.price_chf` | Histogram | Listing rent prices in CHF per search |
| `monitor.evaluations.errors` | Counter | Evaluation errors |
| `monitor.evaluations.prefilter_rejections` | Counter | Listings rejected by the deep_eval prefilter |
| `monitor.listings.detail_fetch_failures` | Counter | Detail page fetch failures during deep_eval |
| `monitor.scrape.rejections` | Counter | Scraping rejected by a portal (403/429) |
| `monitor.run.duration_seconds` | Histogram | Total run duration |
| `monitor.search.duration_seconds` | Histogram | Duration of a single search |
| `monitor.run.last_success_time` | Gauge | Unix epoch of last successful run (heartbeat) |

Traces auto-instrument all `requests` HTTP calls; logs are forwarded from Python's `logging`.

## Deployment

Runs as a Kubernetes CronJob on Hetzner k3s via ArgoCD, with a Grafana dashboard + heartbeat alert — see the `ch-wg-monitor/` and `terraform/grafana/` directories in the `troescher-gitops` repo. The image is built and pushed to `ghcr.io/<owner>/ch-wg-monitor:latest` by `.github/workflows/build.yaml` on push to `main`.
