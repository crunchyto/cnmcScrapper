# CNMC Mobile Carrier Scraper

Bulk-query Spanish mobile carrier info from the CNMC portability checker. Uses Playwright + 2Captcha + Tor IP rotation + SQLite storage with resume support.

## Prerequisites

- **Python 3.10+**
- **Tor** — SOCKS proxy for IP rotation
- **2Captcha account** — API key for automated CAPTCHA solving

### Tor Setup

```bash
# macOS
brew install tor
# Start Tor with control port
tor --SocksPort 9050 --ControlPort 9051 --HashedControlPassword "$(tor --hash-password scraper)"
```

Default config expects Tor on `127.0.0.1:9050` (SOCKS) and `9051` (control).

### 2Captcha

Get an API key at [2captcha.com](https://2captcha.com) and set it in `config.yaml` under `captcha.api_key`.

## Install

```bash
uv sync
uv run playwright install chromium
```

## Usage

```bash
# Basic run (reads phones from config input_csv)
uv run python -m scraper.main

# Specify input CSV
uv run python -m scraper.main --input phones.csv

# Reset progress and start from scratch
uv run python -m scraper.main --reset

# Custom config path
uv run python -m scraper.main --config my_config.yaml
```

### Input CSV

Single-column, no header, one 9-digit Spanish mobile per line (starts with 6 or 7):

```
612345678
711223344
```

## Configuration

Edit `config.yaml`:

```yaml
proxy:
  tor_host: "127.0.0.1"
  tor_port: 9050
  control_port: 9051
  control_password: "scraper"

captcha:
  api_key: "YOUR_2CAPTCHA_KEY"

scraping:
  base_url: "https://numeracionyoperadores.cnmc.es/portabilidad/movil"
  delay_seconds: 2
  rotation_count: 9       # Rotate Tor IP every N queries

input_csv: "phones.csv"

retry:
  max_attempts: 3
  base_delay_seconds: 5

database:
  path: "cnmc.db"

logging:
  level: "INFO"
  file: "scraper.log"
  max_bytes: 10485760     # 10 MB per log file
  backup_count: 5         # Keep 5 rotated backups
```

## Database

SQLite (`cnmc.db`) with two tables:

- **portability** — `phone`, `operator`, `query_date`, `scraped_at`
- **progress** — resume state per CSV file (`csv_file`, `last_line`, `updated_at`)

## How It Works

1. Reads phone numbers from CSV, validates format, deduplicates
2. Checks progress table for resume point
3. For each phone: navigates CNMC form → solves CAPTCHA → submits → parses result → stores in DB
4. Rotates Tor IP every N successful queries to stay under rate limits
5. Retries failures with exponential backoff; rotates IP immediately on blocks
6. Saves progress after each phone for crash-safe resume
7. Graceful shutdown on Ctrl+C
