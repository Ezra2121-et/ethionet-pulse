# EthioNet Pulse (EthioPulse)

**A lightweight network connectivity and reliability monitor designed for Ethiopian organizations.**

EthioNet Pulse helps a school, clinic, office, or small business see whether configured internet targets are reachable, track response time, and keep a history of connectivity problems. Instead of relying only on someone's memory that "the internet was down," it records measurements that can be reviewed later.

> **Project status:** Functional prototype intended for local/self-hosted use. It is not a hosted public monitoring service or a guaranteed SLA monitor.

## Why this project?

Unstable connectivity can interrupt day-to-day work, but small organizations may not have a dedicated network monitoring platform. EthioNet Pulse is a small, self-hosted option that records useful evidence of connectivity and helps make troubleshooting more concrete.

## Features

- **Live connectivity overview** for configured network targets.
- **Scheduled checks** using the system `ping` utility.
- **Latency measurements** and a dashboard latency trend.
- **Persistent history** stored in a local SQLite database.
- **Outage history**, including active/unresolved outage records.
- **Availability statistics** over a requested time window.
- **Measurement coverage reporting** so missing data is not silently counted as uptime.
- **CSV export** for sharing or further analysis.
- **On-demand diagnosis** comparing the local gateway, public targets, system DNS resolution, and configured HTTP(S) services.
- **Continuous HTTP(S) service monitoring** with response times, HTTP status codes, persistent check history, confirmed service incidents, and Telegram outage/recovery alerts.
- **Network quality sampling** using multiple ICMP packets per target to estimate packet loss, min/average/max latency, and jitter where supported by the system ping output.
- **Sustained degradation detection** with consecutive-round thresholds and Telegram recovery notifications.
- **Reliability reporting** combining time-based network availability with measurement coverage, service sample success rates, quality measurements, and incident durations.
- **Optional Telegram alerts** on confirmed outage start and recovery transitions, with consecutive-check thresholds to reduce transient false alarms.
- **JSON API** with an interactive API explorer at `/docs`.
- **Lightweight local deployment** with Python and a local database.

## Technology

- Python 3.11+
- FastAPI and Uvicorn
- SQLAlchemy (async) and SQLite
- Jinja2 templates, HTML, CSS, and JavaScript
- APScheduler for recurring checks

## How it works

1. The scheduler starts a connectivity-check cycle at the configured interval.
2. The monitor pings each configured target and records the timestamp, reachability, latency when available, and any error message.
3. Records are stored in SQLite and used to build status, history, outage, and statistics responses.
4. The dashboard requests the API and displays current status, latency, reachable targets, recent checks, and outage information.
5. An on-demand diagnostic compares the local gateway, public targets, DNS resolution, and configured HTTP service URLs.
6. A separate scheduled job checks configured HTTP(S) services, records response codes and response times in SQLite, and tracks service-specific incidents.
7. Internet and service incidents require consecutive failed checks before being confirmed and consecutive successful checks before recovery. Optional Telegram alerts are emitted only for confirmed transitions.
8. CSV and JSON report endpoints expose measurements and incident history.

### A note on availability statistics

The uptime percentage is an estimate derived from recorded, known online/offline intervals. EthioNet Pulse limits how much time a sample can represent; long gaps are left unmonitored instead of being assumed to be uptime. Check the measurement-coverage values alongside the uptime estimate, especially when the monitor has been stopped or the device has been offline.

## Run locally

These steps assume a Linux development environment with Python 3.11 or newer and the `ping` utility available in your `PATH`.

```bash
git clone https://github.com/Ezra2121-et/ethionet-pulse.git
cd ethionet-pulse

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
```

Check that the system can run ping:

```bash
ping -c 1 1.1.1.1
```

Start the application:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open:

- Dashboard: http://127.0.0.1:8000
- API explorer: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

Stop the server with `Ctrl+C`.

## Run the tests

With the virtual environment activated and dependencies installed, run the standard-library unit tests:

```bash
python -m unittest discover -s tests -v
```

The tests cover monitoring persistence, outage start/recovery thresholds, alert-message formatting, diagnostic scenarios, and the rule that long measurement gaps must not be counted as uptime.

## Connectivity diagnosis

The dashboard includes an on-demand **Run diagnosis** action. It compares a ping to the Linux default gateway with pings to configured public targets, checks hostnames using the system DNS resolver, and optionally requests configured HTTP(S) service URLs. Results include a cautious summary and a suggested next step.

Set `DNS_TEST_HOSTS` to a comma-separated list of hostnames. Set `SERVICE_URLS` to optional comma-separated HTTP(S) endpoints that matter to your organization, such as a public health-check URL. These diagnosis checks do not change stored monitoring history.

This is a troubleshooting aid, not definitive root-cause analysis. Routers, firewalls, or providers may block ICMP ping even when other traffic works. DNS lookup and HTTP service errors also need interpretation in context.

API endpoint: `GET /api/diagnose`.

## Configuration

Edit the local `.env` file before launching the application:

| Setting | Purpose | Default |
| --- | --- | --- |
| `APP_NAME` | Name shown by the application | `EthioNet Pulse` |
| `DATABASE_URL` | SQLite database location | `sqlite+aiosqlite:///./data/ethionet.db` |
| `CHECK_INTERVAL_SECONDS` | Time between check cycles | `30` |
| `INTERNET_TARGETS` | Comma-separated hosts/IP addresses to check | `1.1.1.1,8.8.8.8,9.9.9.9` |
| `REQUEST_TIMEOUT_SECONDS` | Per-target ping timeout | `5` |
| `DNS_TEST_HOSTS` | Comma-separated hostnames for resolver checks | `example.com,cloudflare.com` |
| `SERVICE_URLS` | Comma-separated HTTP(S) services for monitoring and diagnosis | `https://example.com` in `.env.example` |
| `SERVICE_REQUEST_TIMEOUT_SECONDS` | HTTP service request timeout | `10` |
| `SERVICE_FAILURE_THRESHOLD` | Consecutive failed service checks required for an incident | `2` |
| `SERVICE_RECOVERY_THRESHOLD` | Consecutive successful service checks required for recovery | `2` |
| `PING_SAMPLES_PER_CHECK` | Packets sent per quality sample (1–20) | `5` |
| `QUALITY_PING_TIMEOUT_SECONDS` | Per-packet ICMP response timeout | `1` |
| `PACKET_LOSS_WARNING_PERCENT` | Packet loss warning threshold | `20.0` |
| `HIGH_LATENCY_WARNING_MS` | Average latency warning threshold | `400.0` |
| `DEGRADATION_CONSECUTIVE_ROUNDS` | Degraded rounds required to open a quality incident | `3` |
| `QUALITY_RECOVERY_CONSECUTIVE_ROUNDS` | Healthy rounds required to resolve a quality incident | `3` |
| `OUTAGE_FAILURE_THRESHOLD` | Consecutive complete failed rounds needed to confirm an outage | `2` |
| `OUTAGE_RECOVERY_THRESHOLD` | Consecutive successful rounds needed to confirm recovery | `2` |
| `ENABLE_TELEGRAM_ALERTS` | Enable Telegram outage/recovery notifications | `false` |
| `TELEGRAM_BOT_TOKEN` | Private Telegram bot token | empty |
| `TELEGRAM_CHAT_ID` | Telegram destination chat ID | empty |

Keep `.env` and local database files private; they are for local configuration and runtime data, not source control.

### Enable Telegram alerts (optional)

1. Create a Telegram bot using the official `@BotFather` account and copy its bot token.
2. Open a chat with your bot and send `/start`.
3. Obtain the chat ID using Telegram's Bot API `getUpdates` response for your bot, then keep it private.
4. In your local `.env`, set `ENABLE_TELEGRAM_ALERTS=true`, `TELEGRAM_BOT_TOKEN=...`, and `TELEGRAM_CHAT_ID=...`.
5. Restart EthioNet Pulse. Alerts are sent only when the database records a new confirmed outage or a recovery. Missing credentials or Telegram delivery failures are logged without stopping monitoring.

Never commit your real bot token or private chat configuration to GitHub.

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Verify that the application is responding |
| GET | `/api/status` | Current status for configured targets |
| GET | `/api/diagnose` | On-demand gateway, public-target, DNS, and configured HTTP service checks |
| GET | `/api/services` | Latest status for each configured HTTP service |
| GET | `/api/services/history?limit=100` | Stored HTTP service check history |
| GET | `/api/service-outages?limit=10` | Confirmed service incidents and recovery durations |
| GET | `/api/quality` | Latest packet loss and latency quality for each network target |
| GET | `/api/quality/history?limit=100` | Historical multi-packet quality samples |
| GET | `/api/quality-incidents?limit=10` | Sustained degradation and recovery incidents |
| GET | `/api/reports/reliability?hours=24` | JSON summary of network, service, and quality reliability |
| GET | `/api/history?limit=100` | Recent connectivity checks |
| GET | `/api/outages?limit=100` | Recent outage records |
| GET | `/api/statistics?hours=24` | Availability, measurement coverage, latency, and outage summaries |
| GET | `/api/reports/csv?hours=24` | Export recent measurements and overlapping outage records as CSV |
| GET | `/docs` | Interactive API explorer |

Statistics accept a time window from 1 to 168 hours; history and outage endpoints accept a limit from 1 to 1,000 records.

## Demo checklist

For the summer-camp presentation:

1. Start the app and show the dashboard updating from the local API.
2. Point out reachable targets, average latency, recent checks, and outage information.
3. Open `/docs` and run `/health`, `/api/status`, and `/api/statistics?hours=24`.
4. Show the continuously monitored HTTP service and its response code, response time, history, and confirmed incident section.
5. Show packet loss, latency, and jitter samples, then explain that sustained quality degradation triggers an alert only after consecutive checks.
6. Open the reliability summary and export the CSV to show measurements and incident history; point out that sample success rate is not the same as time-based uptime.
7. Click **Run diagnosis** and explain how gateway, DNS, public-target, and HTTP results guide troubleshooting without claiming definitive root cause.

A private speaking outline is maintained separately from this public repository.

## Known limitations and future work

- ICMP ping can be blocked by a destination or network even when other services work; packet-loss warnings require context and are not proof that all internet access is unavailable. Compare them with HTTP checks where possible.
- This prototype is intended to run as a local, single-instance monitor. A public managed deployment, customer accounts, durable multi-process alert queues, and central multi-site monitoring are not part of the demonstrated baseline.
- HTTP checks only test the specific URLs configured in `SERVICE_URLS`; they do not prove every function within a service works. Configure safe GET-compatible health endpoints and avoid embedding credentials or secrets in URL query strings.
- Telegram alerts are optional and require the operator to configure a bot token and chat ID locally.
- Multi-site monitoring, customer accounts, a hosted service, and automatic root-cause detection remain future work.

## Author

**Yosef Getnet**  
GitHub: [Ezra2121-et](https://github.com/Ezra2121-et)
