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
- If port 16888 is already in use, print a clear error message (`Port 16888 is already in use. Is coinwar config already running?`) and exit cleanly — no Python traceback.
- Server confirms it is listening before calling `webbrowser.open` (open browser from within a Flask startup hook, not before `app.run`).
- Server runs until the user presses Ctrl+C.

---

## Components

### `crypto/config_server.py`
- Flask app with three routes.
- `read_env()` — parses `.env` into a dict (key=value, skips comments).
- `write_env(key, value)` — updates a single key in `.env` in-place using atomic write (write to `.env.tmp` then `os.replace`), preserving comments and order.
- `read_yaml(path)` — loads a yaml config file; returns `{}` if file is missing (never raises).
- `write_yaml(path, key_path, value)` — updates a nested key in a yaml file. `key_path` is validated against a server-side allowlist (see Tab Contents table); unknown paths return 400 and are not written.

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
| 進階設定 | `config/crypto_settings.yaml` | `arbitrage.min_spread_pct`, `arbitrage.cooldown_seconds`, `position.max_usdt`, `position.min_usdt` *(phase 1 only — remaining yaml keys such as `exchanges.*.enabled`, `monitor.*`, `backtest.*` are out of scope)* |

---

## Data Flow

1. User runs `coinwar config`.
2. Flask starts on port 16888; browser opens automatically after server confirms it is listening.
3. Page loads → `GET /api/config` returns all current values as:
   ```json
   {
     "env": {"FINMIND_TOKEN": "...", "BINANCE_API_KEY": "", ...},
     "yaml": {"arbitrage.min_spread_pct": 0.005, ...}
   }
   ```
   Missing `.env` fields default to `""`. Missing yaml file returns `"yaml": {}`. Never returns null.
4. User edits a field → `POST /api/save {source: "env"|"yaml", key: "BINANCE_API_KEY", value: "..."}`.
5. Server validates key against allowlist; writes atomically to disk; responds `{"ok": true}` or `{"ok": false, "error": "..."}`.
6. Page shows "已儲存" next to the field for 2 seconds (or "錯誤" on failure).

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
