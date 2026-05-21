import sqlite3
from core.config import DATABASE_PATH

CREATE_TABLES_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ========================
-- 原有表（保留兼容）
-- ========================
CREATE TABLE IF NOT EXISTS fixed_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_no        TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    category        TEXT,
    spec            TEXT,
    qty             INTEGER NOT NULL DEFAULT 1,
    unit_price      REAL    DEFAULT 0,
    total_value     REAL    DEFAULT 0,
    purchase_date   TEXT,
    department      TEXT,
    location        TEXT,
    manager         TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'in_use',
    remark          TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS office_supplies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_no         TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    category        TEXT,
    spec            TEXT,
    unit            TEXT    NOT NULL DEFAULT '个',
    current_qty     REAL    NOT NULL DEFAULT 0,
    safety_qty      REAL    DEFAULT 0,
    remark          TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS supply_inbound (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    inbound_no      TEXT    NOT NULL UNIQUE,
    supply_id       INTEGER NOT NULL,
    qty             REAL    NOT NULL,
    unit_price      REAL    DEFAULT 0,
    supplier        TEXT,
    inbound_date    TEXT    NOT NULL DEFAULT (date('now','localtime')),
    remark          TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (supply_id) REFERENCES office_supplies(id)
);

CREATE TABLE IF NOT EXISTS supply_outbound (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    outbound_no     TEXT    NOT NULL UNIQUE,
    supply_id       INTEGER NOT NULL,
    qty             REAL    NOT NULL,
    receiver        TEXT    NOT NULL,
    department      TEXT,
    purpose         TEXT,
    outbound_date   TEXT    NOT NULL DEFAULT (date('now','localtime')),
    remark          TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (supply_id) REFERENCES office_supplies(id)
);

-- ========================
-- 仓库结构（3层）
-- ========================
CREATE TABLE IF NOT EXISTS warehouses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    address     TEXT,
    manager     TEXT,
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS warehouse_areas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    warehouse_id    INTEGER NOT NULL,
    code            TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    area_type       TEXT    NOT NULL DEFAULT 'ambient',  -- ambient/cold/hazardous
    temp_min        REAL,
    temp_max        REAL,
    status          TEXT    NOT NULL DEFAULT 'active',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(warehouse_id, code),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
);

CREATE TABLE IF NOT EXISTS locations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id         INTEGER NOT NULL,
    code            TEXT    NOT NULL,          -- 如 A-01-02-03
    zone_code       TEXT,                      -- A
    row_no          INTEGER,                   -- 01 排
    col_no          INTEGER,                   -- 02 列
    level_no        INTEGER,                   -- 03 层
    capacity        REAL    DEFAULT 1,         -- 最大容量（体积/重量/托盘数）
    current_load    REAL    DEFAULT 0,         -- 当前负载
    status          TEXT    NOT NULL DEFAULT 'empty',  -- empty/occupied/frozen
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(area_id, code),
    FOREIGN KEY (area_id) REFERENCES warehouse_areas(id)
);

-- ========================
-- 物料/SKU 主数据
-- ========================
CREATE TABLE IF NOT EXISTS skus (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_code        TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    category        TEXT,
    spec            TEXT,
    unit            TEXT    NOT NULL DEFAULT '件',
    barcode         TEXT,
    shelf_life_days INTEGER,                   -- 效期天数
    abc_class       TEXT    DEFAULT 'C',       -- A/B/C
    safety_stock    REAL    DEFAULT 0,
    max_stock       REAL    DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'active',
    remark          TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sku_packages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id          INTEGER NOT NULL,
    package_type    TEXT    NOT NULL,           -- box/pallet/piece
    conversion_qty  REAL    NOT NULL DEFAULT 1, -- 换算成基础单位的数量
    barcode         TEXT,
    length          REAL,
    width           REAL,
    height          REAL,
    weight          REAL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (sku_id) REFERENCES skus(id)
);

-- ========================
-- 往来单位
-- ========================
CREATE TABLE IF NOT EXISTS partners (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    partner_type    TEXT    NOT NULL DEFAULT 'supplier',  -- supplier/customer/both
    contact_person  TEXT,
    contact_phone   TEXT,
    address         TEXT,
    status          TEXT    NOT NULL DEFAULT 'active',
    remark          TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ========================
-- 容器管理
-- ========================
CREATE TABLE IF NOT EXISTS containers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL UNIQUE,
    container_type  TEXT    NOT NULL DEFAULT 'pallet',  -- pallet/tote/rack
    capacity        REAL    DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'idle',     -- idle/in_use/damaged
    location_id     INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (location_id) REFERENCES locations(id)
);

-- ========================
-- 入库管理
-- ========================
CREATE TABLE IF NOT EXISTS asn_headers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asn_no          TEXT    NOT NULL UNIQUE,
    partner_id      INTEGER NOT NULL,
    warehouse_id    INTEGER NOT NULL,
    asn_type        TEXT    NOT NULL DEFAULT 'purchase',  -- purchase/return/transfer/other
    status          TEXT    NOT NULL DEFAULT 'draft',      -- draft/receiving/received/cancelled
    expected_date   TEXT,
    remark          TEXT,
    created_by      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (partner_id) REFERENCES partners(id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
);

CREATE TABLE IF NOT EXISTS asn_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asn_id          INTEGER NOT NULL,
    line_no         INTEGER NOT NULL,
    sku_id          INTEGER NOT NULL,
    expected_qty    REAL    NOT NULL,
    received_qty    REAL    DEFAULT 0,
    batch_no        TEXT,
    production_date TEXT,
    expiry_date     TEXT,
    remark          TEXT,
    FOREIGN KEY (asn_id) REFERENCES asn_headers(id),
    FOREIGN KEY (sku_id) REFERENCES skus(id)
);

CREATE TABLE IF NOT EXISTS receipt_headers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_no      TEXT    NOT NULL UNIQUE,
    asn_id          INTEGER,
    warehouse_id    INTEGER NOT NULL,
    receipt_type    TEXT    NOT NULL DEFAULT 'purchase',  -- purchase/return/transfer/surplus/gift
    status          TEXT    NOT NULL DEFAULT 'pending',    -- pending/qc_done/putaway_done/confirmed
    receipt_date    TEXT    NOT NULL DEFAULT (date('now','localtime')),
    qc_inspector    TEXT,                                 -- 质检人
    remark          TEXT,
    created_by      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (asn_id) REFERENCES asn_headers(id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
);

CREATE TABLE IF NOT EXISTS receipt_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id      INTEGER NOT NULL,
    line_no         INTEGER NOT NULL,
    sku_id          INTEGER NOT NULL,
    received_qty    REAL    NOT NULL,
    accepted_qty    REAL    DEFAULT 0,      -- 质检合格数
    rejected_qty    REAL    DEFAULT 0,      -- 质检不合格数
    batch_no        TEXT,
    production_date TEXT,
    expiry_date     TEXT,
    qc_result       TEXT    DEFAULT 'pending',  -- pending/pass/fail
    qc_remark       TEXT,
    remark          TEXT,
    FOREIGN KEY (receipt_id) REFERENCES receipt_headers(id),
    FOREIGN KEY (sku_id) REFERENCES skus(id)
);

CREATE TABLE IF NOT EXISTS putaway_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_line_id INTEGER NOT NULL,
    sku_id          INTEGER NOT NULL,
    from_location_id INTEGER,               -- 收货暂存区
    to_location_id  INTEGER,                -- 推荐上架库位
    qty             REAL    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending/completed
    completed_by    TEXT,
    completed_at    TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (receipt_line_id) REFERENCES receipt_lines(id),
    FOREIGN KEY (sku_id) REFERENCES skus(id),
    FOREIGN KEY (to_location_id) REFERENCES locations(id)
);

-- ========================
-- 出库管理
-- ========================
CREATE TABLE IF NOT EXISTS so_headers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    so_no           TEXT    NOT NULL UNIQUE,
    partner_id      INTEGER NOT NULL,
    warehouse_id    INTEGER NOT NULL,
    so_type         TEXT    NOT NULL DEFAULT 'sale',  -- sale/picking/transfer
    status          TEXT    NOT NULL DEFAULT 'draft',  -- draft/released/waving/picking/packing/shipped/cancelled
    priority        INTEGER DEFAULT 5,                -- 1最高 5普通
    scheduled_date  TEXT,
    remark          TEXT,
    created_by      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (partner_id) REFERENCES partners(id),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
);

CREATE TABLE IF NOT EXISTS so_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    so_id           INTEGER NOT NULL,
    line_no         INTEGER NOT NULL,
    sku_id          INTEGER NOT NULL,
    ordered_qty     REAL    NOT NULL,
    allocated_qty   REAL    DEFAULT 0,
    picked_qty      REAL    DEFAULT 0,
    shipped_qty     REAL    DEFAULT 0,
    remark          TEXT,
    FOREIGN KEY (so_id) REFERENCES so_headers(id),
    FOREIGN KEY (sku_id) REFERENCES skus(id)
);

CREATE TABLE IF NOT EXISTS wave_headers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wave_no         TEXT    NOT NULL UNIQUE,
    warehouse_id    INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'created',  -- created/assigned/picking/picked/packed/shipped
    created_by      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
);

CREATE TABLE IF NOT EXISTS wave_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wave_id         INTEGER NOT NULL,
    so_line_id      INTEGER NOT NULL,
    sku_id          INTEGER NOT NULL,
    location_id     INTEGER NOT NULL,
    batch_no        TEXT,
    allocated_qty   REAL    NOT NULL,
    picked_qty      REAL    DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending/picked/short
    FOREIGN KEY (wave_id) REFERENCES wave_headers(id),
    FOREIGN KEY (so_line_id) REFERENCES so_lines(id),
    FOREIGN KEY (sku_id) REFERENCES skus(id),
    FOREIGN KEY (location_id) REFERENCES locations(id)
);

CREATE TABLE IF NOT EXISTS pick_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wave_id         INTEGER NOT NULL,
    wave_line_id    INTEGER NOT NULL,
    sku_id          INTEGER NOT NULL,
    location_id     INTEGER NOT NULL,
    qty             REAL    NOT NULL,
    picked_qty      REAL    DEFAULT 0,
    pick_order      INTEGER NOT NULL DEFAULT 0,  -- 拣货路径顺序
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending/picked/short
    picked_by       TEXT,
    picked_at       TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (wave_id) REFERENCES wave_headers(id),
    FOREIGN KEY (wave_line_id) REFERENCES wave_lines(id),
    FOREIGN KEY (sku_id) REFERENCES skus(id),
    FOREIGN KEY (location_id) REFERENCES locations(id)
);

-- ========================
-- 库存核心
-- ========================
CREATE TABLE IF NOT EXISTS inventory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id          INTEGER NOT NULL,
    location_id     INTEGER NOT NULL,
    batch_no        TEXT    DEFAULT '',
    qty             REAL    NOT NULL DEFAULT 0,
    frozen_qty      REAL    DEFAULT 0,
    production_date TEXT,
    expiry_date     TEXT,
    status          TEXT    NOT NULL DEFAULT 'available',  -- available/frozen/rejected
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(sku_id, location_id, batch_no),
    FOREIGN KEY (sku_id) REFERENCES skus(id),
    FOREIGN KEY (location_id) REFERENCES locations(id)
);

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id              INTEGER NOT NULL,
    location_id         INTEGER NOT NULL,
    batch_no            TEXT    DEFAULT '',
    transaction_type    TEXT    NOT NULL,   -- inbound/outbound/move/freeze/release/count_adjust
    qty_change          REAL    NOT NULL,   -- 正数=增加 负数=减少
    balance_qty         REAL    NOT NULL,   -- 变动后结存
    reference_type      TEXT,               -- asn/receipt/so/wave/count_plan/stock_move
    reference_no        TEXT,
    reference_line_id   INTEGER,
    operator            TEXT,
    remark              TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (sku_id) REFERENCES skus(id),
    FOREIGN KEY (location_id) REFERENCES locations(id)
);

-- ========================
-- 库内作业
-- ========================
CREATE TABLE IF NOT EXISTS count_plans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_no         TEXT    NOT NULL UNIQUE,
    warehouse_id    INTEGER NOT NULL,
    area_id         INTEGER,
    count_type      TEXT    NOT NULL DEFAULT 'blind',  -- open/blind/cycle/movement
    status          TEXT    NOT NULL DEFAULT 'created', -- created/counting/done/adjusted
    created_by      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id),
    FOREIGN KEY (area_id) REFERENCES warehouse_areas(id)
);

CREATE TABLE IF NOT EXISTS count_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL,
    location_id     INTEGER NOT NULL,
    sku_id          INTEGER,
    batch_no        TEXT,
    system_qty      REAL    DEFAULT 0,
    count_qty       REAL,                   -- 实盘数（盲盘时先为空）
    difference      REAL,
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending/counted/done
    counted_by      TEXT,
    counted_at      TEXT,
    remark          TEXT,
    FOREIGN KEY (plan_id) REFERENCES count_plans(id),
    FOREIGN KEY (location_id) REFERENCES locations(id),
    FOREIGN KEY (sku_id) REFERENCES skus(id)
);

CREATE TABLE IF NOT EXISTS stock_moves (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    move_no         TEXT    NOT NULL UNIQUE,
    sku_id          INTEGER NOT NULL,
    from_location_id INTEGER NOT NULL,
    to_location_id  INTEGER NOT NULL,
    batch_no        TEXT,
    qty             REAL    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'completed',
    moved_by        TEXT,
    remark          TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (sku_id) REFERENCES skus(id),
    FOREIGN KEY (from_location_id) REFERENCES locations(id),
    FOREIGN KEY (to_location_id) REFERENCES locations(id)
);

CREATE TABLE IF NOT EXISTS inventory_blocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id    INTEGER NOT NULL,
    block_type      TEXT    NOT NULL DEFAULT 'qc',    -- qc/abnormal/other
    frozen_qty      REAL    NOT NULL,
    released_qty    REAL    DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'frozen', -- frozen/released
    reason          TEXT,
    created_by      TEXT,
    released_by     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    released_at     TEXT,
    FOREIGN KEY (inventory_id) REFERENCES inventory(id)
);

-- ========================
-- 索引
-- ========================
CREATE INDEX IF NOT EXISTS idx_assets_category ON fixed_assets(category);
CREATE INDEX IF NOT EXISTS idx_assets_status ON fixed_assets(status);
CREATE INDEX IF NOT EXISTS idx_assets_manager ON fixed_assets(manager);
CREATE INDEX IF NOT EXISTS idx_supplies_category ON office_supplies(category);
CREATE INDEX IF NOT EXISTS idx_inbound_supply ON supply_inbound(supply_id);
CREATE INDEX IF NOT EXISTS idx_outbound_supply ON supply_outbound(supply_id);
CREATE INDEX IF NOT EXISTS idx_inbound_date ON supply_inbound(inbound_date);
CREATE INDEX IF NOT EXISTS idx_outbound_date ON supply_outbound(outbound_date);

CREATE INDEX IF NOT EXISTS idx_areas_warehouse ON warehouse_areas(warehouse_id);
CREATE INDEX IF NOT EXISTS idx_locations_area ON locations(area_id);
CREATE INDEX IF NOT EXISTS idx_locations_status ON locations(status);
CREATE INDEX IF NOT EXISTS idx_skus_category ON skus(category);
CREATE INDEX IF NOT EXISTS idx_skus_abc ON skus(abc_class);
CREATE INDEX IF NOT EXISTS idx_skus_barcode ON skus(barcode);
CREATE INDEX IF NOT EXISTS idx_packages_sku ON sku_packages(sku_id);
CREATE INDEX IF NOT EXISTS idx_partners_type ON partners(partner_type);
CREATE INDEX IF NOT EXISTS idx_asn_partner ON asn_headers(partner_id);
CREATE INDEX IF NOT EXISTS idx_asn_status ON asn_headers(status);
CREATE INDEX IF NOT EXISTS idx_asn_lines_asn ON asn_lines(asn_id);
CREATE INDEX IF NOT EXISTS idx_receipt_asn ON receipt_headers(asn_id);
CREATE INDEX IF NOT EXISTS idx_receipt_status ON receipt_headers(status);
CREATE INDEX IF NOT EXISTS idx_receipt_lines ON receipt_lines(receipt_id);
CREATE INDEX IF NOT EXISTS idx_putaway_status ON putaway_tasks(status);
CREATE INDEX IF NOT EXISTS idx_so_partner ON so_headers(partner_id);
CREATE INDEX IF NOT EXISTS idx_so_status ON so_headers(status);
CREATE INDEX IF NOT EXISTS idx_so_lines ON so_lines(so_id);
CREATE INDEX IF NOT EXISTS idx_wave_status ON wave_headers(status);
CREATE INDEX IF NOT EXISTS idx_wave_lines_wave ON wave_lines(wave_id);
CREATE INDEX IF NOT EXISTS idx_pick_wave ON pick_tasks(wave_id);
CREATE INDEX IF NOT EXISTS idx_pick_status ON pick_tasks(status);
CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory(sku_id);
CREATE INDEX IF NOT EXISTS idx_inventory_location ON inventory(location_id);
CREATE INDEX IF NOT EXISTS idx_inventory_expiry ON inventory(expiry_date);
CREATE INDEX IF NOT EXISTS idx_trans_sku ON inventory_transactions(sku_id);
CREATE INDEX IF NOT EXISTS idx_trans_type ON inventory_transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_trans_ref ON inventory_transactions(reference_no);
CREATE INDEX IF NOT EXISTS idx_trans_created ON inventory_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_count_plans_status ON count_plans(status);
CREATE INDEX IF NOT EXISTS idx_count_tasks_plan ON count_tasks(plan_id);
CREATE INDEX IF NOT EXISTS idx_count_tasks_status ON count_tasks(status);
CREATE INDEX IF NOT EXISTS idx_stock_moves_sku ON stock_moves(sku_id);
CREATE INDEX IF NOT EXISTS idx_blocks_inventory ON inventory_blocks(inventory_id);
"""


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.executescript(CREATE_TABLES_SQL)
        # 迁移：已有数据库添加后续新增的列
        migrations = [
            "ALTER TABLE receipt_headers ADD COLUMN qc_inspector TEXT",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # 列已存在，跳过
