# Michelin Scraper

Scrapes restaurant data from the Michelin Guide with change tracking.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
# Full scrape
python -m scraper.main --full

# Full scrape with limit
python -m scraper.main --full --limit 50

# Incremental update (only changed restaurants)
python -m scraper.main --update
```

## Configuration

Edit `config.yaml`:

```yaml
proxy:
  enabled: false
  server: "http://proxy:8080"

scraping:
  batch_size: 25
  batch_delay_seconds: 10

database:
  path: "restaurants.db"
```

## Database

SQLite with two tables:
- `restaurants` - current restaurant data
- `restaurant_history` - snapshots of changed records

## Change Log

Changes logged to `additions.txt`:
```
[2024-01-15 10:30:00] ADDED: Restaurant Name (michelin_id)
[2024-01-15 10:30:01] MODIFIED: Restaurant Name (michelin_id)
```

## Cron

Weekly update:
```cron
0 3 * * 0 cd /path/to/testRalph && python -m scraper.main --update >> /var/log/michelin.log 2>&1
```
