from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates

router = APIRouter(prefix="/inventory")


@router.get("")
def list_inventory(request: Request, sku_id: str = "", location_id: str = "", batch_no: str = "",
                   warehouse_id: str = "", db=Depends(get_db)):
    sql = """
        SELECT i.*, s.name as sku_name, s.sku_code, s.unit,
               l.code as location_code,
               a.name as area_name, a.code as area_code,
               w.name as warehouse_name
        FROM inventory i
        JOIN skus s ON i.sku_id=s.id
        JOIN locations l ON i.location_id=l.id
        JOIN warehouse_areas a ON l.area_id=a.id
        JOIN warehouses w ON a.warehouse_id=w.id
        WHERE 1=1
    """
    params = []
    if sku_id:
        sql += " AND i.sku_id=?"
        params.append(int(sku_id))
    if location_id:
        sql += " AND i.location_id=?"
        params.append(int(location_id))
    if batch_no:
        sql += " AND i.batch_no LIKE ?"
        params.append(f"%{batch_no}%")
    if warehouse_id:
        sql += " AND w.id=?"
        params.append(int(warehouse_id))
    sql += " ORDER BY w.name, a.code, l.code, s.sku_code"

    rows = db.execute(sql, params).fetchall()

    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    skus = db.execute("SELECT * FROM skus WHERE status='active'").fetchall()

    return templates.TemplateResponse("inventory/list.html", {
        "request": request, "active_page": "inventory",
        "rows": rows, "sku_id": sku_id, "location_id": location_id, "batch_no": batch_no,
        "warehouse_id": warehouse_id, "warehouses": warehouses, "skus_list": skus,
    })


@router.get("/transactions")
def list_transactions(request: Request, sku_id: str = "", type: str = "",
                      reference_no: str = "", date_from: str = "", date_to: str = "",
                      db=Depends(get_db)):
    sql = """
        SELECT t.*, s.name as sku_name, s.sku_code,
               l.code as location_code
        FROM inventory_transactions t
        JOIN skus s ON t.sku_id=s.id
        JOIN locations l ON t.location_id=l.id
        WHERE 1=1
    """
    params = []
    if sku_id:
        sql += " AND t.sku_id=?"
        params.append(int(sku_id))
    if type:
        sql += " AND t.transaction_type=?"
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
