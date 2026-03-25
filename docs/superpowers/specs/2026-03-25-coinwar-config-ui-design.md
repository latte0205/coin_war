# coinwar config UI — Design Spec

**Date:** 2026-03-25
**Status:** Approved

---

## Overview

Add a `coinwar config` subcommand that launches a local Flask web server and opens a browser-based settings page. Users can update API keys and system configuration through a tabbed UI with instant save on every field change.

---

## Architecture

```
coinwar config
  └── crypto/config_server.py  (Flask app)
       ├── GET  /               → serve config_ui.html
       ├── GET  /api/config     → read .env + yaml, return JSON
       └── POST /api/save       → write field change to .env or yaml
```

- Server binds to `127.0.0.1:16888` (fixed port).
- On startup, Python opens the URL in the default browser (`webbrowser.open`).
- Server runs until the user presses Ctrl+C.

---

## Components

### `crypto/config_server.py`
- Flask app with three routes.
- `read_env()` — parses `.env` into a dict (key=value, skips comments).
- `write_env(key, value)` — updates a single key in `.env` in-place, preserving comments and order.
- `read_yaml(path)` — loads a yaml config file.
- `write_yaml(path, key_path, value)` — updates a nested key in a yaml file (e.g. `arbitrage.min_spread_pct`).

### `crypto/config_ui.html`
- Static HTML file served by Flask.
- Three tabs: **台股設定**, **加密貨幣**, **進階設定**.
- On page load: `GET /api/config` to populate all fields.
- On each field `change` event: `POST /api/save` with `{source, key, value}`.
- Shows a brief inline "已儲存" confirmation per field (no full-page reload).

### `main.py` — new `config` subcommand
- Calls `crypto/config_server.run()`.

---

## Tab Contents

| Tab | Source | Fields |
|-----|--------|--------|
| 台股設定 | `.env` | `FINMIND_TOKEN`, `BROKER_API_KEY`, `BROKER_API_SECRET` |
| 加密貨幣 | `.env` | `BINANCE_API_KEY/SECRET`, `OKX_API_KEY/SECRET/PASSPHRASE`, `BYBIT_API_KEY/SECRET`, `MAX_API_KEY/SECRET`, `BITOPRO_API_KEY/SECRET` |
| 進階設定 | `config/crypto_settings.yaml` | `arbitrage.min_spread_pct`, `arbitrage.cooldown_seconds`, `position.max_usdt`, `position.min_usdt` |

---

## Data Flow

1. User runs `coinwar config`.
2. Flask starts on a free port; browser opens automatically.
3. Page loads → `GET /api/config` returns all current values.
4. User edits a field → `POST /api/save {source: "env"|"yaml", key: "BINANCE_API_KEY", value: "..."}`.
5. Server writes the change to disk; responds `{ok: true}`.
6. Page shows "已儲存" next to the field for 2 seconds.

---

## Error Handling

- If `.env` does not exist, create it from `.env.example`.
- If a yaml file is missing, return empty values for that tab (don't crash).
- Sensitive fields (API keys/secrets) render as `type="password"` with a show/hide toggle.

---

## Dependencies

- `flask` — add to `requirements.txt`.
- No new dependencies for the frontend (vanilla JS).

---

## Out of Scope

- Authentication (local-only, no need).
- Editing `config/settings.yaml` (watchlist, etc.) — can be added later.
- Dark/light theme toggle.
