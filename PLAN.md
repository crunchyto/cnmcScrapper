# CNMC mobile phones scrapper - Multi-Phase Implementation

## Project Structure

```
cnmcScrapper/
├── scraper/
│   ├── __init__.py
│   ├── main.py           # Entry point, CLI
│   ├── browser.py        # Playwright setup, proxy config
│   ├── parser.py         # HTML parsing, field extraction
│   ├── database.py       # SQLite ops, history tracking
│   ├── proxy_pool.py     # Tor-based proxy rotation via stem
│   └── utils.py          # Hashing, retry logic, logging
├── scripts/
│   └── fetch_proxies.py  # Free proxy fetcher (fallback, not primary)
├── config.yaml           # Proxy, batch size, delays
├── requirements.txt
├── additions.txt         # Change log (auto-generated)
└── README.md
```

