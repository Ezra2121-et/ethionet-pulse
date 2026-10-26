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
5. A CSV endpoint exports measurements and relevant outage records.

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

The tests cover connectivity-round classification and verify that long gaps between measurements are left unmonitored rather than counted as uptime.

## Connectivity diagnosis

The dashboard includes an on-demand **Run diagnosis** action. It compares a ping to the Linux default gateway with pings to configured public targets, then suggests what to investigate based on the results.

This is a troubleshooting aid, not definitive root-cause analysis. Routers, firewalls, or providers may block ICMP ping even when other traffic works. The diagnosis does not change stored monitoring history.

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

Keep `.env` and local database files private; they are for local configuration and runtime data, not source control.

## API endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Verify that the application is responding |
| GET | `/api/status` | Current status for configured targets |
| GET | `/api/diagnose` | On-demand gateway and public-target checks with cautious troubleshooting guidance |
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
4. Export the CSV and briefly show the measurements it contains.
5. Click **Run diagnosis** and explain how local-gateway and external-target results guide troubleshooting without proving root cause.
6. Explain the monitoring loop, SQLite history, and why gaps are not automatically counted as uptime.

See [the presentation video script](docs/DEMO_SCRIPT.md) for a concise speaking outline.

## Known limitations and future work

- ICMP ping can be blocked by a destination or network even when other services work; a failed ping alone is not proof that all internet access is unavailable.
- This prototype is intended to run on a local host. A public, managed deployment, user accounts, and long-term remote alerting are not part of the demonstrated baseline.
- Possible next improvements include optional notifications, configurable target groups, multi-site monitoring, and packaging as a system service.

## Author

**Yosef Getnet**  
GitHub: [Ezra2121-et](https://github.com/Ezra2121-et)
