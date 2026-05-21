# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

WMS 仓储管理系统 — evolved from a simple asset/supply management system into a full warehouse management system. FastAPI + SQLite + Jinja2 server-side rendering + Bootstrap 5. Everything is Chinese-language UI. No API/JSON endpoints — all responses are HTML pages or redirects.

## Run / develop

```bash
python main.py          # starts on http://localhost:8000 (0.0.0.0)
```

Or double-click `启动资产管理系统.bat`. The bat file starts the server in a minimized window and opens the browser.

There are no tests, no linters, no build step. Dependencies: `fastapi`, `uvicorn`, `jinja2` (and `python-multipart` for form parsing). SQLite is in the stdlib.

## Architecture

Three layers: **core/** (config + database), **routers/** (11 FastAPI router modules), **templates/** (Jinja2 organized by module subdirectories).

### `core/database.py`
- 23 tables defined in one `CREATE_TABLES_SQL` string executed at startup
- WAL mode + foreign keys ON
- `get_db()` — FastAPI dependency that yields a `sqlite3.Row` connection (WAL mode, foreign keys)
- `init_db()` — runs `CREATE TABLE IF NOT EXISTS` for all tables (idempotent, safe to call every launch)

### `core/config.py`
- `DATABASE_PATH = "assets.db"` (single-file SQLite database)
- All status/type constants and their Chinese labels (AREA_TYPES, LOCATION_STATUSES, ABC_CLASSES, etc.)
- `DEFAULT_EXPIRY_WARNING_DAYS = 30`
- `templates = Jinja2Templates(directory="templates")` — single global instance used by all routers

### `utils/helpers.py`
- `_generate_code(db, prefix, table, column)` — produces codes like `WH202605210001` (prefix + YYYYMMDD + 4-digit seq)
- `safe_create(db, do_insert, max_retries=3)` — retries on `sqlite3.IntegrityError` (handles code collisions). The `do_insert` callback is re-invoked so a fresh code is generated each retry.
- `calc_expiry_date()`, `is_near_expiry()` — date helpers
- `write_transaction()` — appends to `inventory_transactions` after reading current balance
- `upsert_inventory()` — insert or update inventory row, raises `ValueError` if qty would go negative
- `update_location_load()` — recalculates location `current_load` and updates status (empty/occupied/frozen)

### `main.py`
- Lifespan calls `init_db()` on startup
- Custom 422 handler: catches `RequestValidationError`, extracts field names, builds Chinese error messages, redirects back to `Referer` with `?error=...` query param
- Static files mounted at `/static`
- 11 routers registered (order matters — dashboard `/` must come before others for the root catch)

### Routers (all under `routers/`)
Each router file is self-contained CRUD for its domain. Patterns:
- **Form validation**: Core forms (fixed_asset, office_supply, warehouse, sku, partner) use `Form("")` defaults + manual `if not field:` checks that re-render the form template with an `error` context variable. WMS workflow forms (inbound, outbound, internal) still use `Form(...)` — the 422 handler in main.py catches those.
- **POST always returns `RedirectResponse("/prefix", 303)`** on success — PRG pattern. Never returns a 200 on successful mutation.
- **Entity-not-found guard**: nearly every edit/detail GET checks `if not record:` and redirects to list.
- **`safe_create` wrapper**: used around INSERT+COMMIT blocks in handlers that generate codes.

### Templates
`templates/base.html` defines the shell: Apple-style sidebar (`active_page` variable highlights current nav item), CSS variables for the color palette, print `@media` styles, location grid styles, and `#form-error` alert div populated by JS from URL `?error=` param.

Form templates use `{% if error %}...{% endif %}` blocks to show validation errors. The `asset`/`supply`/`warehouse` etc. context variable serves dual purpose: when it has an `id`, the form posts to the edit URL; when it has no `id` (validation re-render for new records), it posts to the create URL.

### Database tables (original + WMS)

| Domain | Tables |
|--------|--------|
| Legacy | `fixed_assets`, `office_supplies`, `supply_inbound`, `supply_outbound` |
| Warehouse structure | `warehouses` → `warehouse_areas` → `locations` (3-tier, UNIQUE area+code) |
| Master data | `skus`, `sku_packages`, `partners`, `containers` |
| Inbound | `asn_headers` → `asn_lines`, `receipt_headers` → `receipt_lines`, `putaway_tasks` |
| Outbound | `so_headers` → `so_lines`, `wave_headers` → `wave_lines`, `pick_tasks` |
| Inventory core | `inventory` (UNIQUE sku+location+batch), `inventory_transactions` |
| Internal ops | `count_plans` → `count_tasks`, `stock_moves`, `inventory_blocks` |

### Key WMS algorithms (in routers)

- **Putaway recommendation** (`inbound.py:_get_putaway_recommendation`): 1) same-SKU adjacent empty locations → 2) ABC zone priority → 3) any empty location
- **FEFO allocation** (`outbound.py:_fefo_allocate`): orders by `expiry_date ASC NULLS LAST`, allocates until qty satisfied, raises `ValueError` on insufficient stock
- **Pick path ordering**: pick tasks assigned with `pick_order` sorted by zone→row→col→level
- **Movement-based counting** (`internal.py`): selects locations with transactions in the last 7 days
- **Location status**: auto-maintained by `update_location_load()` — 0 or negative → `empty`, positive → `occupied`, frozen flag preserved

## 422 validation handling

Never add `Form(...)` (required) to new form handlers. Use `Form("")` or `Form(None)` defaults, then validate manually in the function body and re-render the form template with `error="..."` when validation fails. This preserves the user's filled-in data and avoids the redirect.
