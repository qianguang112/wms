from fastapi import APIRouter, Request, Depends
from core.database import get_db
from core.config import templates, ASSET_STATUS_IN_USE, ASSET_STATUS_IDLE, ASSET_STATUS_SCRAPPED, DEFAULT_EXPIRY_WARNING_DAYS

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db=Depends(get_db)):
    # 原有资产统计
    row = db.execute(
        f"""SELECT
            COUNT(*) as asset_count,
            COALESCE(SUM(CASE WHEN status!='{ASSET_STATUS_SCRAPPED}' THEN qty * unit_price ELSE 0 END), 0) as asset_value,
            COALESCE(SUM(CASE WHEN status='{ASSET_STATUS_IN_USE}' THEN 1 ELSE 0 END), 0) as in_use,
            COALESCE(SUM(CASE WHEN status='{ASSET_STATUS_IDLE}' THEN 1 ELSE 0 END), 0) as idle,
            COALESCE(SUM(CASE WHEN status='{ASSET_STATUS_SCRAPPED}' THEN 1 ELSE 0 END), 0) as scrapped
        FROM fixed_assets"""
    ).fetchone()

    supply_count = db.execute("SELECT COUNT(*) as c FROM office_supplies").fetchone()["c"]
    warning_count = db.execute(
        "SELECT COUNT(*) as c FROM office_supplies WHERE current_qty <= safety_qty AND safety_qty > 0"
    ).fetchone()["c"]

    today = db.execute("SELECT date('now','localtime') as d").fetchone()["d"]
    today_inbound = db.execute(
        "SELECT COUNT(*) as c FROM supply_inbound WHERE inbound_date=?", (today,)
    ).fetchone()["c"]
    today_outbound = db.execute(
        "SELECT COUNT(*) as c FROM supply_outbound WHERE outbound_date=?", (today,)
    ).fetchone()["c"]

    location_stats = db.execute(
        "SELECT location, COUNT(*) as cnt FROM fixed_assets WHERE location IS NOT NULL AND location != '' GROUP BY location ORDER BY cnt DESC"
    ).fetchall()

    # WMS 统计
    sku_count = db.execute("SELECT COUNT(*) as c FROM skus WHERE status='active'").fetchone()["c"]

    loc_total = db.execute("SELECT COUNT(*) as c FROM locations").fetchone()["c"]
    loc_occupied = db.execute("SELECT COUNT(*) as c FROM locations WHERE status='occupied'").fetchone()["c"]

    near_expiry_count = db.execute(
        "SELECT COUNT(*) as c FROM inventory WHERE expiry_date IS NOT NULL AND expiry_date <= date('now','localtime',?) AND qty > 0",
        (f"+{DEFAULT_EXPIRY_WARNING_DAYS} days",)
    ).fetchone()["c"]

    pending_receipt = db.execute(
        "SELECT COUNT(*) as c FROM receipt_headers WHERE status IN ('pending','qc_done')"
    ).fetchone()["c"]

    pending_putaway = db.execute(
        "SELECT COUNT(*) as c FROM receipt_headers WHERE status='qc_done'"
    ).fetchone()["c"]

    pending_pick = db.execute(
        "SELECT COUNT(*) as c FROM pick_tasks WHERE status='pending'"
    ).fetchone()["c"]

    pending_ship = db.execute(
        "SELECT COUNT(*) as c FROM wave_headers WHERE status IN ('picked','packed')"
    ).fetchone()["c"]

    frozen_count = db.execute(
        "SELECT COUNT(*) as c FROM inventory_blocks WHERE status='frozen'"
    ).fetchone()["c"]

    wms_today_inbound = db.execute(
        "SELECT COUNT(*) as c FROM receipt_headers WHERE receipt_date=?", (today,)
    ).fetchone()["c"]

    wms_today_outbound = db.execute(
        "SELECT COUNT(*) as c FROM wave_headers WHERE status='shipped' AND updated_at LIKE ?",
        (f"{today}%",)
    ).fetchone()["c"]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        # 原有
        "asset_count": row["asset_count"],
        "asset_value": row["asset_value"],
        "in_use": row["in_use"],
        "idle": row["idle"],
        "scrapped": row["scrapped"],
        "supply_count": supply_count,
        "warning_count": warning_count,
        "today_inbound": today_inbound,
        "today_outbound": today_outbound,
        "location_stats": location_stats,
        # WMS
        "sku_count": sku_count,
        "loc_total": loc_total,
        "loc_occupied": loc_occupied,
        "near_expiry_count": near_expiry_count,
        "pending_receipt": pending_receipt,
        "pending_putaway": pending_putaway,
        "pending_pick": pending_pick,
        "pending_ship": pending_ship,
        "frozen_count": frozen_count,
        "wms_today_inbound": wms_today_inbound,
        "wms_today_outbound": wms_today_outbound,
    })
