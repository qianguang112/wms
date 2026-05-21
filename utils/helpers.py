from datetime import datetime, date, timedelta
import sqlite3


def _generate_code(db: sqlite3.Connection, prefix: str, table: str, column: str) -> str:
    """通用编号生成: 前缀+年月日+4位流水号"""
    today = datetime.now().strftime("%Y%m%d")
    row = db.execute(
        f"SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY {column} DESC LIMIT 1",
        (f"{prefix}{today}%",)
    ).fetchone()
    if row:
        seq = int(row[column][-4:]) + 1
    else:
        seq = 1
    return f"{prefix}{today}{seq:04d}"


def safe_create(db: sqlite3.Connection, do_insert, max_retries=3):
    """执行插入并在并发冲突时重试。do_insert 会被重复调用以重新生成编号。"""
    for attempt in range(max_retries):
        try:
            do_insert()
            return
        except sqlite3.IntegrityError:
            if attempt == max_retries - 1:
                raise


# 原有编号生成器
def generate_asset_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "FA", "fixed_assets", "asset_no")


def generate_item_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "IT", "office_supplies", "item_no")


def generate_inbound_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "IN", "supply_inbound", "inbound_no")


def generate_outbound_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "OUT", "supply_outbound", "outbound_no")


# WMS 编号生成器
def generate_warehouse_code(db: sqlite3.Connection) -> str:
    return _generate_code(db, "WH", "warehouses", "code")


def generate_area_code(db: sqlite3.Connection) -> str:
    return _generate_code(db, "AR", "warehouse_areas", "code")


def generate_sku_code(db: sqlite3.Connection) -> str:
    return _generate_code(db, "SK", "skus", "sku_code")


def generate_partner_code(db: sqlite3.Connection) -> str:
    return _generate_code(db, "BP", "partners", "code")


def generate_container_code(db: sqlite3.Connection) -> str:
    return _generate_code(db, "CT", "containers", "code")


def generate_asn_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "ASN", "asn_headers", "asn_no")


def generate_receipt_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "RCV", "receipt_headers", "receipt_no")


def generate_so_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "SO", "so_headers", "so_no")


def generate_wave_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "WV", "wave_headers", "wave_no")


def generate_count_plan_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "CNT", "count_plans", "plan_no")


def generate_move_no(db: sqlite3.Connection) -> str:
    return _generate_code(db, "MV", "stock_moves", "move_no")


def calc_expiry_date(production_date: str, shelf_life_days: int) -> str:
    """根据生产日期和效期天数计算到期日"""
    if not production_date or not shelf_life_days:
        return None
    prod = datetime.strptime(production_date, "%Y-%m-%d")
    expiry = prod + timedelta(days=shelf_life_days)
    return expiry.strftime("%Y-%m-%d")


def is_near_expiry(expiry_date: str, warning_days: int = 30) -> bool:
    """判断是否近效期"""
    if not expiry_date:
        return False
    exp = datetime.strptime(expiry_date, "%Y-%m-%d").date()
    return (exp - date.today()).days <= warning_days


def write_transaction(db: sqlite3.Connection, *,
                      sku_id: int, location_id: int, batch_no: str = "",
                      transaction_type: str, qty_change: float,
                      reference_type: str, reference_no: str,
                      reference_line_id: int = None, operator: str = "", remark: str = ""):
    """写入库存流水。先查当前结存，再写入变动。"""
    inv = db.execute(
        "SELECT qty FROM inventory WHERE sku_id=? AND location_id=? AND batch_no=?",
        (sku_id, location_id, batch_no)
    ).fetchone()
    balance_qty = inv["qty"] if inv else 0

    db.execute(
        """INSERT INTO inventory_transactions
           (sku_id, location_id, batch_no, transaction_type, qty_change, balance_qty,
            reference_type, reference_no, reference_line_id, operator, remark)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (sku_id, location_id, batch_no, transaction_type, qty_change, balance_qty,
         reference_type, reference_no, reference_line_id, operator, remark)
    )


def upsert_inventory(db: sqlite3.Connection, *,
                     sku_id: int, location_id: int, batch_no: str = "",
                     qty_change: float):
    """更新或插入库存记录。qty_change 正数为入库，负数为出库。"""
    existing = db.execute(
        "SELECT id, qty FROM inventory WHERE sku_id=? AND location_id=? AND batch_no=?",
        (sku_id, location_id, batch_no)
    ).fetchone()

    if existing:
        new_qty = existing["qty"] + qty_change
        if new_qty < 0:
            raise ValueError(f"库存不足: SKU={sku_id} 库位={location_id} 批次={batch_no}")
        db.execute(
            "UPDATE inventory SET qty=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_qty, existing["id"])
        )
    else:
        if qty_change < 0:
            raise ValueError(f"库存不足: SKU={sku_id} 库位={location_id} 批次={batch_no}")
        db.execute(
            """INSERT INTO inventory (sku_id, location_id, batch_no, qty)
               VALUES (?,?,?,?)""",
            (sku_id, location_id, batch_no, qty_change)
        )


def update_location_load(db: sqlite3.Connection, location_id: int):
    """根据 inventory 重新计算库位负载并更新状态"""
    row = db.execute(
        "SELECT COALESCE(SUM(qty), 0) as total FROM inventory WHERE location_id=?",
        (location_id,)
    ).fetchone()
    total_qty = row["total"]
    loc = db.execute("SELECT capacity, status FROM locations WHERE id=?", (location_id,)).fetchone()
    if not loc:
        return
    current_load = total_qty
    if loc["status"] == "frozen":
        new_status = "frozen"
    elif current_load <= 0:
        new_status = "empty"
    else:
        new_status = "occupied"
    db.execute(
        "UPDATE locations SET current_load=?, status=?, updated_at=datetime('now','localtime') WHERE id=?",
        (current_load, new_status, location_id)
    )
