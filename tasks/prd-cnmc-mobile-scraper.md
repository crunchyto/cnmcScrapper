# PRD: CNMC Mobile Number Carrier Scraper

## Introduction

Python CLI tool to bulk-query Spanish mobile phone carrier info from CNMC's portability checker (https://numeracionyoperadores.cnmc.es/portabilidad/movil). Reads phone numbers from a CSV, automates form submission via Playwright, solves CAPTCHA via 2Captcha API, rotates IP via Tor every 9 queries (10/IP/day limit), stores results in SQLite, and supports resume across runs.

Replaces existing Michelin scraper code, reusing its architecture (browser automation, Tor proxy rotation, SQLite, config, logging).

## Goals

- Bulk-query carrier info for Spanish mobile numbers from CNMC
- Fully automated: no manual intervention (2Captcha for CAPTCHA solving)
- Respect CNMC's 10 queries/IP/day limit via Tor IP rotation every 9 queries
- Resume interrupted scraping sessions without re-processing already-scraped numbers
- Persistent storage of results in SQLite

## User Stories

### US-001: Read phone numbers from CSV
**Description:** As a user, I want to provide a CSV file with phone numbers so the script processes them in order.

**Acceptance Criteria:**
- [ ] Reads CSV file path from CLI argument or config.yaml
- [ ] CSV format: single column, no header, one phone per line
- [ ] Validates phone format (9-digit Spanish mobile: starts with 6 or 7)
- [ ] Skips blank lines and duplicates
- [ ] Logs total count of valid numbers found

### US-002: Automate CNMC form submission
**Description:** As a user, I want the script to automatically fill and submit the CNMC form for each phone number.

**Acceptance Criteria:**
- [ ] Navigates to https://numeracionyoperadores.cnmc.es/portabilidad/movil
- [ ] Fills phone number input field
- [ ] Solves CAPTCHA via 2Captcha API integration
- [ ] Submits form and waits for response
- [ ] Handles form errors (invalid number, service unavailable)
- [ ] Retries on transient failures (max 3 attempts with backoff)

### US-003: Parse and store results
**Description:** As a user, I want scraped carrier data stored in SQLite so I can query it later.

**Acceptance Criteria:**
- [ ] Parses response: phone number, operator name, query timestamp
- [ ] Stores in SQLite `portability` table with columns: phone, operator, query_date, scraped_at
- [ ] Upserts on phone number (updates if re-scraped)
- [ ] Logs each successful result

### US-004: Tor IP rotation every 9 queries
**Description:** As a user, I want automatic IP rotation to avoid hitting the 10 queries/IP/day cap.

**Acceptance Criteria:**
- [ ] After every 9 successful queries, sends NEWNYM signal via stem
- [ ] Waits minimum 10s for new Tor circuit
- [ ] Verifies new IP before continuing (optional: log IP change)
- [ ] Counter resets after rotation
- [ ] All browser traffic routes through Tor proxy (127.0.0.1:8118)

### US-005: Resume capability
**Description:** As a user, I want to stop and restart the script without losing progress.

**Acceptance Criteria:**
- [ ] Tracks last processed CSV line index in SQLite `progress` table
- [ ] On startup, reads last index and skips already-processed phones
- [ ] Allows `--reset` flag to start from beginning
- [ ] Logs resume point on startup ("Resuming from line X of Y")

### US-006: Logging
**Description:** As a user, I want detailed logs to monitor progress and debug issues.

**Acceptance Criteria:**
- [ ] Rotating file log (10MB, 5 backups) + console output
- [ ] Logs: phone being queried, result, IP rotations, errors, resume point
- [ ] Configurable log level via config.yaml
- [ ] Timestamps on all entries

## Functional Requirements

- FR-1: CLI entry point accepting `--input <csv_path>` and optional `--reset` flag
- FR-2: CSV reader loads phones, validates format (9 digits, starts with 6/7), deduplicates
- FR-3: Playwright browser launches in headless mode with Tor SOCKS proxy, webdriver masking, random user-agent
- FR-4: For each phone: navigate form → fill number → solve CAPTCHA via 2Captcha → submit → parse response
- FR-5: 2Captcha integration: detect CAPTCHA sitekey from page, send to 2Captcha API, poll for solution, inject token
- FR-6: Parse response HTML/text for "Número de teléfono", "Operador actual", "Fecha consulta"
- FR-7: Store result in SQLite `portability` table (phone TEXT PRIMARY KEY, operator TEXT, query_date TEXT, scraped_at TEXT)
- FR-8: After every 9 successful queries, rotate Tor IP via stem NEWNYM, wait 10s, reset counter
- FR-9: Track progress in SQLite `progress` table (csv_file TEXT, last_line INT, updated_at TEXT)
- FR-10: On startup, check progress table and skip already-processed lines
- FR-11: Retry failed queries up to 3 times with exponential backoff (5s base)
- FR-12: On CAPTCHA failure or IP block, rotate IP immediately and retry
- FR-13: Graceful shutdown on SIGINT: save progress, close browser, close DB

## Non-Goals

- No CSV/report export (query SQLite directly)
- No web UI or dashboard
- No batch/parallel browser instances
- No proxy sources beyond Tor
- No phone number generation or enumeration

## Technical Considerations

- **Reuse from existing codebase:**
  - `scraper/browser.py` → adapt for CNMC form interaction (keep webdriver masking, user-agent rotation)
  - `scraper/proxy_pool.py` → reuse Tor/stem rotation as-is, change trigger from page-based to count-based (every 9)
  - `scraper/database.py` → new schema but same SQLite wrapper pattern
  - `scraper/utils.py` → reuse config loader and logging setup
  - `config.yaml` → adapt fields for CNMC-specific config
- **New dependency:** `2captcha-python` (official 2Captcha SDK)
- **CAPTCHA flow:** Inspect page for reCAPTCHA sitekey → send solve request to 2Captcha → poll result → inject `g-recaptcha-response` token → submit form
- **Tor setup prerequisite:** Tor daemon + Privoxy running (127.0.0.1:8118 HTTP proxy, 9051 control port)
- **Rate limiting:** Hardcoded 9-query rotation. Add configurable delay between queries (default 3-5s random)

## Success Metrics

- Scrapes 100+ phones unattended in single run
- Resume works correctly across interrupted sessions (0 re-processed phones)
- IP rotation prevents any 429/block responses from CNMC
- CAPTCHA solve rate >90% via 2Captcha

## Open Questions

1. What is the exact CAPTCHA type on the CNMC form? (reCAPTCHA v2, v3, hCaptcha?) — needs manual inspection
2. Does CNMC rate-limit per session/cookie in addition to IP? May need to clear cookies on rotation
3. Does the form use AJAX or full page reload for results? Affects parsing strategy
4. Is there a delay/queue on 2Captcha during peak hours that could slow throughput?
