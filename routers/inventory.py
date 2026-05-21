from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates

router = APIRouter(prefix="/inventory")

INVENTORY_STATUSES = ["available", "frozen", "rejected"]
INVENTORY_STATUS_LABELS = {"available": "可用", "frozen": "冻结", "rejected": "不合格"}


# ======================== SKU 汇总视图 ========================
@router.get("")
def list_inventory(request: Request, warehouse_id: str = "", search: str = "",
                   db=Depends(get_db)):
    sql = """
        SELECT s.id as sku_id, s.sku_code, s.name as sku_name, s.unit,
               COALESCE(SUM(i.qty), 0) as total_qty,
               COALESCE(SUM(i.frozen_qty), 0) as frozen_qty,
               COUNT(DISTINCT i.location_id) as location_count
        FROM inventory i
        JOIN skus s ON i.sku_id = s.id
        JOIN locations l ON i.location_id = l.id
        JOIN warehouse_areas a ON l.area_id = a.id
        WHERE i.qty > 0
    """
    params = []
    if warehouse_id:
        sql += " AND a.warehouse_id = ?"
        params.append(int(warehouse_id))
    if search:
        sql += " AND (s.sku_code LIKE ? OR s.name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    sql += " GROUP BY s.id ORDER BY s.sku_code"

    rows = db.execute(sql, params).fetchall()
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()

    return templates.TemplateResponse("inventory/list.html", {
        "request": request, "active_page": "inventory",
        "rows": rows, "warehouse_id": warehouse_id, "search": search,
        "warehouses": warehouses,
    })


# ======================== SKU 库位明细 ========================
@router.get("/sku/{sku_id}")
def sku_detail(sku_id: int, request: Request, warehouse_id: str = "",
               batch_no: str = "", db=Depends(get_db)):
    sku = db.execute("SELECT * FROM skus WHERE id=?", (sku_id,)).fetchone()
    if not sku:
        return RedirectResponse("/inventory", 303)

    sql = """
        SELECT i.*, l.code as location_code,
               a.name as area_name, a.code as area_code,
               w.name as warehouse_name, w.id as warehouse_id
        FROM inventory i
        JOIN locations l ON i.location_id = l.id
        JOIN warehouse_areas a ON l.area_id = a.id
        JOIN warehouses w ON a.warehouse_id = w.id
        WHERE i.sku_id = ? AND i.qty > 0
    """
    params = [sku_id]
    if warehouse_id:
        sql += " AND w.id = ?"
        params.append(int(warehouse_id))
    if batch_no:
        sql += " AND i.batch_no LIKE ?"
        params.append(f"%{batch_no}%")
    sql += " ORDER BY w.name, a.code, l.code, i.batch_no"

    rows = db.execute(sql, params).fetchall()

    # 该 SKU 汇总
    summary = db.execute(
        """SELECT COALESCE(SUM(qty), 0) as total_qty,
                  COALESCE(SUM(frozen_qty), 0) as frozen_qty
           FROM inventory WHERE sku_id = ? AND qty > 0""",
        (sku_id,)
    ).fetchone()

    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()

    return templates.TemplateResponse("inventory/sku_detail.html", {
        "request": request, "active_page": "inventory",
        "sku": sku, "rows": rows, "summary": summary,
        "warehouse_id": warehouse_id, "batch_no": batch_no,
        "warehouses": warehouses,
    })


# ======================== 编辑 ========================
@router.get("/{id}/edit")
def edit_form(id: int, request: Request, db=Depends(get_db)):
    inv = db.execute("""
        SELECT i.*, s.name as sku_name, s.sku_code,
               l.code as location_code,
               a.name as area_name, a.code as area_code,
               w.name as warehouse_name
        FROM inventory i
        JOIN skus s ON i.sku_id = s.id
        JOIN locations l ON i.location_id = l.id
        JOIN warehouse_areas a ON l.area_id = a.id
        JOIN warehouses w ON a.warehouse_id = w.id
        WHERE i.id = ?
    """, (id,)).fetchone()
    if not inv:
        return RedirectResponse("/inventory", 303)

    skus = db.execute("SELECT * FROM skus WHERE status='active' ORDER BY sku_code").fetchall()
    locations = db.execute("""
        SELECT l.*, a.name as area_name, a.code as area_code, w.name as warehouse_name
        FROM locations l
        JOIN warehouse_areas a ON l.area_id = a.id
        JOIN warehouses w ON a.warehouse_id = w.id
        WHERE l.status != 'locked' OR l.status IS NULL
        ORDER BY w.name, a.code, l.code
    """).fetchall()

    return templates.TemplateResponse("inventory/form.html", {
        "request": request, "active_page": "inventory",
        "inv": inv, "skus": skus, "locations": locations,
        "statuses": INVENTORY_STATUSES, "status_labels": INVENTORY_STATUS_LABELS,
    })


@router.post("/{id}/edit")
def update(id: int, request: Request, sku_id: str = Form(""), location_id: str = Form(""),
           batch_no: str = Form(""), qty: str = Form(""), frozen_qty: str = Form(""),
           production_date: str = Form(""), expiry_date: str = Form(""),
           status: str = Form("available"), db=Depends(get_db)):
    inv = db.execute("SELECT * FROM inventory WHERE id = ?", (id,)).fetchone()
    if not inv:
        return RedirectResponse("/inventory", 303)

    original_sku_id = inv["sku_id"]

    if not sku_id or not location_id or not qty:
        skus = db.execute("SELECT * FROM skus WHERE status='active' ORDER BY sku_code").fetchall()
        locations = db.execute("""
            SELECT l.*, a.name as area_name, a.code as area_code, w.name as warehouse_name
            FROM locations l
            JOIN warehouse_areas a ON l.area_id = a.id
            JOIN warehouses w ON a.warehouse_id = w.id
            WHERE l.status != 'locked' OR l.status IS NULL
            ORDER BY w.name, a.code, l.code
        """).fetchall()
        return templates.TemplateResponse("inventory/form.html", {
            "request": request, "active_page": "inventory",
            "inv": {"id": id, "sku_id": int(sku_id) if sku_id else 0, "location_id": int(location_id) if location_id else 0,
                    "batch_no": batch_no, "qty": qty, "frozen_qty": frozen_qty,
                    "production_date": production_date, "expiry_date": expiry_date, "status": status,
                    "sku_name": "", "sku_code": "", "location_code": "", "area_name": "", "warehouse_name": ""},
            "skus": skus, "locations": locations,
            "statuses": INVENTORY_STATUSES, "status_labels": INVENTORY_STATUS_LABELS,
            "error": "请填写必填字段：SKU、库位、数量",
        })

    qty_val = float(qty)
    frozen_val = float(frozen_qty) if frozen_qty else 0
    new_sku_id = int(sku_id)
    db.execute(
        """UPDATE inventory SET sku_id = ?, location_id = ?, batch_no = ?, qty = ?, frozen_qty = ?,
           production_date = ?, expiry_date = ?, status = ?, updated_at = datetime('now','localtime')
           WHERE id = ?""",
        (new_sku_id, int(location_id), batch_no, qty_val, frozen_val,
         production_date or None, expiry_date or None, status, id)
    )
    db.commit()
    return RedirectResponse(f"/inventory/sku/{new_sku_id}", 303)


# ======================== 删除 ========================
@router.post("/{id}/delete")
def delete(id: int, db=Depends(get_db)):
    inv = db.execute("SELECT sku_id FROM inventory WHERE id = ?", (id,)).fetchone()
    sku_id = inv["sku_id"] if inv else None
    db.execute("DELETE FROM inventory WHERE id = ?", (id,))
    db.commit()

    if sku_id:
        remaining = db.execute(
            "SELECT COUNT(*) as c FROM inventory WHERE sku_id = ? AND qty > 0", (sku_id,)
        ).fetchone()
        if remaining and remaining["c"] > 0:
            return RedirectResponse(f"/inventory/sku/{sku_id}", 303)
    return RedirectResponse("/inventory", 303)


# ======================== 库存流水 ========================
@router.get("/transactions")
def list_transactions(request: Request, sku_id: str = "", type: str = "",
                      reference_no: str = "", date_from: str = "", date_to: str = "",
                      db=Depends(get_db)):
    sql = """
        SELECT t.*, s.name as sku_name, s.sku_code,
               l.code as location_code
        FROM inventory_transactions t
        JOIN skus s ON t.sku_id = s.id
        JOIN locations l ON t.location_id = l.id
        WHERE 1=1
    """
    params = []
    if sku_id:
        sql += " AND t.sku_id = ?"
        params.append(int(sku_id))
    if type:
        sql += " AND t.transaction_type = ?"
        params.append(type)
    if reference_no:
        sql += " AND t.reference_no LIKE ?"
        params.append(f"%{reference_no}%")
    if date_from:
        sql += " AND t.created_at >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND t.created_at <= ?"
        params.append(date_to + " 23:59:59")
    sql += " ORDER BY t.id DESC LIMIT 500"

    rows = db.execute(sql, params).fetchall()
    skus = db.execute("SELECT * FROM skus WHERE status='active'").fetchall()

    return templates.TemplateResponse("inventory/transactions.html", {
        "request": request, "active_page": "inventory",
        "rows": rows, "sku_id": sku_id, "type": type,
        "reference_no": reference_no, "date_from": date_from, "date_to": date_to,
        "skus_list": skus,
    })
