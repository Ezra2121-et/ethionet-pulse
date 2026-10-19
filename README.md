# EthioNet Pulse

**Lightweight Network & Outage Resilience Monitor for Ethiopian Organizations**

EthioNet Pulse is a free, self-hosted tool that continuously monitors internet connectivity and local network health. It records outages with accurate timestamps and generates clear daily and weekly reports that non-technical managers can easily understand.

Designed for the realities of Ethiopian offices, schools, clinics, and small businesses — frequent power cuts and unstable internet.

## Features (Version 1.0)

- Continuous internet connectivity monitoring
- Outage detection with start time, end time, and duration
- Simple classification of issues (Internet / Local Network / Possible Power Event)
- Clean web dashboard
- Daily and weekly reports
- Telegram alerts (optional)
- Runs as a systemd service
- Extremely lightweight (works on modest hardware)

## Tech Stack

- Python 3.11+
- FastAPI
- SQLite
- HTMX + Jinja2
- systemd

## Status

Currently under active development.

## Author

Yosef Getnet  
GitHub: [Ezra2121-et](https://github.com/Ezra2121-et)
