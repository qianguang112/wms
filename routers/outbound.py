from datetime import date
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates, SO_TYPES, SO_TYPE_LABELS, DEFAULT_EXPIRY_WARNING_DAYS
from utils.helpers import (generate_so_no, generate_wave_no, safe_create,
                           write_transaction, upsert_inventory, update_location_load, is_near_expiry)

router = APIRouter(prefix="/outbound")


def _fefo_allocate(db, sku_id: int, warehouse_id: int, need_qty: float):
    """FEFO分配：按效期从早到晚分配库存"""
    rows = db.execute(
        """SELECT i.*, l.code as location_code
           FROM inventory i
           JOIN locations l ON i.location_id = l.id
           JOIN warehouse_areas a ON l.area_id = a.id
           WHERE i.sku_id=? AND a.warehouse_id=? AND i.qty > i.frozen_qty AND i.status='available'
           ORDER BY i.expiry_date ASC NULLS LAST""",
        (sku_id, warehouse_id)
    ).fetchall()

    result = []
    remaining = need_qty
    for inv in rows:
        if remaining <= 0:
            break
        available = inv["qty"] - inv["frozen_qty"]
        take = min(available, remaining)
        result.append({
            "inventory_id": inv["id"],
            "location_id": inv["location_id"],
            "location_code": inv["location_code"],
            "batch_no": inv["batch_no"],
            "expiry_date": inv["expiry_date"],
            "take_qty": take,
        })
        remaining -= take

    if remaining > 0:
        raise ValueError(f"库存不足: SKU={sku_id} 缺 {remaining}")

    return result


# ======================== 出库列表 ========================
@router.get("")
def list_outbound(request: Request, type: str = "", status: str = "", db=Depends(get_db)):
    sql = "SELECT s.*, w.name as warehouse_name, p.name as partner_name FROM so_headers s JOIN warehouses w ON s.warehouse_id=w.id JOIN partners p ON s.partner_id=p.id WHERE 1=1"
    params = []
    if type:
        sql += " AND s.so_type=?"
        params.append(type)
    if status:
        sql += " AND s.status=?"
        params.append(status)
    sql += " ORDER BY s.id DESC"
    rows = db.execute(sql, params).fetchall()
    return templates.TemplateResponse("outbound/list.html", {
        "request": request, "active_page": "outbound",
        "rows": rows, "type": type, "status": status,
        "so_types": SO_TYPES, "so_type_labels": SO_TYPE_LABELS,
    })


# ======================== SO ========================
@router.get("/so/new")
def new_so_form(request: Request, db=Depends(get_db)):
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    partners = db.execute("SELECT * FROM partners WHERE partner_type IN ('customer','both') AND status='active'").fetchall()
    skus = db.execute("SELECT * FROM skus WHERE status='active'").fetchall()
    return templates.TemplateResponse("outbound/so_form.html", {
        "request": request, "active_page": "outbound",
        "warehouses": warehouses, "partners": partners, "skus": skus,
        "so_types": SO_TYPES, "so_type_labels": SO_TYPE_LABELS,
    })


@router.post("/so/new")
def create_so(warehouse_id: int = Form(...), partner_id: int = Form(...),
              so_type: str = Form("sale"), scheduled_date: str = Form(""),
              priority: int = Form(5), remark: str = Form(""), created_by: str = Form(""),
              sku_ids: list = Form(...), ordered_qtys: list = Form(...),
              db=Depends(get_db)):

    def do_insert():
        so_no = generate_so_no(db)
        db.execute(
            """INSERT INTO so_headers (so_no, partner_id, warehouse_id, so_type, scheduled_date, priority, remark, created_by)
               VALUES (?,?,?,?,?,?,?,?)""",
            (so_no, partner_id, warehouse_id, so_type, scheduled_date or None, priority, remark, created_by)
        )
        so_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        for i in range(len(sku_ids)):
            db.execute(
                "INSERT INTO so_lines (so_id, line_no, sku_id, ordered_qty) VALUES (?,?,?,?)",
                (so_id, i + 1, int(sku_ids[i]), float(ordered_qtys[i]))
            )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/outbound", 303)


@router.get("/so/{id}")
def so_detail(id: int, request: Request, db=Depends(get_db)):
    so = db.execute(
        """SELECT s.*, w.name as warehouse_name, p.name as partner_name
           FROM so_headers s JOIN warehouses w ON s.warehouse_id=w.id JOIN partners p ON s.partner_id=p.id
           WHERE s.id=?""", (id,)
    ).fetchone()
    if not so:
        return RedirectResponse("/outbound", 303)
    lines = db.execute(
        """SELECT l.*, s.name as sku_name, s.sku_code, s.unit
           FROM so_lines l JOIN skus s ON l.sku_id=s.id WHERE l.so_id=?""", (id,)
    ).fetchall()
    return templates.TemplateResponse("outbound/so_detail.html", {
        "request": request, "active_page": "outbound", "so": so, "lines": lines,
        "so_type_labels": SO_TYPE_LABELS,
    })


# ======================== 波次 ========================
@router.post("/so/{id}/create-wave")
def create_wave(id: int, created_by: str = Form(""), db=Depends(get_db)):
    so = db.execute("SELECT * FROM so_headers WHERE id=?", (id,)).fetchone()
    if not so:
        return RedirectResponse("/outbound", 303)

    def do_insert():
        wave_no = generate_wave_no(db)
        db.execute(
            "INSERT INTO wave_headers (wave_no, warehouse_id, created_by) VALUES (?,?,?)",
            (wave_no, so["warehouse_id"], created_by)
        )
        wave_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]

        lines = db.execute("SELECT * FROM so_lines WHERE so_id=?", (id,)).fetchall()
        for line in lines:
            if line["ordered_qty"] <= line["allocated_qty"]:
                continue
            need_qty = line["ordered_qty"] - line["allocated_qty"]
            # FEFO分配
            allocs = _fefo_allocate(db, line["sku_id"], so["warehouse_id"], need_qty)
            for a in allocs:
                db.execute(
                    """INSERT INTO wave_lines (wave_id, so_line_id, sku_id, location_id, batch_no, allocated_qty)
                       VALUES (?,?,?,?,?,?)""",
                    (wave_id, line["id"], line["sku_id"], a["location_id"], a["batch_no"], a["take_qty"])
                )
                # 检验FEFO：如果有近效期批号被跳过则告警（在pick_task中标记）
            db.execute(
                "UPDATE so_lines SET allocated_qty=allocated_qty+? WHERE id=?",
                (need_qty, line["id"])
            )
        db.execute("UPDATE so_headers SET status='waving', updated_at=datetime('now','localtime') WHERE id=?", (id,))
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse(f"/outbound", 303)


@router.get("/wave/{id}")
def wave_detail(id: int, request: Request, db=Depends(get_db)):
    wave = db.execute(
        """SELECT w.*, wh.name as warehouse_name
           FROM wave_headers w JOIN warehouses wh ON w.warehouse_id=wh.id WHERE w.id=?""", (id,)
    ).fetchone()
    if not wave:
        return RedirectResponse("/outbound", 303)
    lines = db.execute(
        """SELECT wl.*, s.name as sku_name, s.sku_code, s.unit, l.code as location_code
           FROM wave_lines wl JOIN skus s ON wl.sku_id=s.id JOIN locations l ON wl.location_id=l.id
           WHERE wl.wave_id=? ORDER BY l.code""", (id,)
    ).fetchall()
    # 近效期告警
    warnings = []
    for line in lines:
        if line["batch_no"] and is_near_expiry(line.get("expiry_date")):
            real_expiry = db.execute(
                "SELECT expiry_date FROM inventory WHERE sku_id=? AND location_id=? AND batch_no=?",
                (line["sku_id"], line["location_id"], line["batch_no"])
            ).fetchone()
            if real_expiry and real_expiry["expiry_date"]:
                if is_near_expiry(real_expiry["expiry_date"], DEFAULT_EXPIRY_WARNING_DAYS):
                    warnings.append(f"SKU {line['sku_code']} 批次 {line['batch_no']} 库位 {line['location_code']} 近效期 {real_expiry['expiry_date']}")
    return templates.TemplateResponse("outbound/wave_detail.html", {
        "request": request, "active_page": "outbound", "wave": wave, "lines": lines, "warnings": warnings,
    })


# ======================== 拣货 ========================
@router.post("/wave/{id}/assign")
def assign_pick_tasks(id: int, operator: str = Form(""), db=Depends(get_db)):
    wave = db.execute("SELECT * FROM wave_headers WHERE id=?", (id,)).fetchone()
    if not wave:
        return RedirectResponse("/outbound", 303)

    # 按库位排序分配拣货顺序
    lines = db.execute(
        """SELECT wl.*, l.code as location_code
           FROM wave_lines wl JOIN locations l ON wl.location_id=l.id
           WHERE wl.wave_id=? ORDER BY l.zone_code, l.row_no, l.col_no, l.level_no""",
        (id,)
    ).fetchall()

    for i, line in enumerate(lines):
        db.execute(
            """INSERT INTO pick_tasks (wave_id, wave_line_id, sku_id, location_id, qty, pick_order)
               VALUES (?,?,?,?,?,?)""",
            (id, line["id"], line["sku_id"], line["location_id"], line["allocated_qty"], i + 1)
        )
    db.execute("UPDATE wave_headers SET status='assigned', updated_at=datetime('now','localtime') WHERE id=?", (id,))
    db.commit()
    return RedirectResponse(f"/outbound/wave/{id}", 303)


@router.get("/wave/{id}/pick")
def pick_execute(id: int, request: Request, db=Depends(get_db)):
    wave = db.execute(
        """SELECT w.*, wh.name as warehouse_name
           FROM wave_headers w JOIN warehouses wh ON w.warehouse_id=wh.id WHERE w.id=?""", (id,)
    ).fetchone()
    if not wave:
        return RedirectResponse("/outbound", 303)

    tasks = db.execute(
        """SELECT pt.*, s.name as sku_name, s.sku_code, s.unit, s.barcode,
                  l.code as location_code, wl.batch_no
           FROM pick_tasks pt
           JOIN skus s ON pt.sku_id=s.id
           JOIN locations l ON pt.location_id=l.id
           JOIN wave_lines wl ON pt.wave_line_id=wl.id
           WHERE pt.wave_id=?
           ORDER BY pt.pick_order""",
        (id,)
    ).fetchall()

    # 统计
    total = sum(t["qty"] for t in tasks)
    picked = sum(t["picked_qty"] for t in tasks)

    return templates.TemplateResponse("outbound/pick.html", {
        "request": request, "active_page": "outbound", "wave": wave,
        "tasks": tasks, "total": total, "picked": picked,
    })


@router.post("/wave/{id}/pick/confirm")
def confirm_pick(id: int, task_ids: list = Form(...), picked_qtys: list = Form(...),
                 operator: str = Form(""), db=Depends(get_db)):
    for i in range(len(task_ids)):
        tid = int(task_ids[i])
        pqty = float(picked_qtys[i]) if picked_qtys[i] else 0
        task = db.execute("SELECT * FROM pick_tasks WHERE id=?", (tid,)).fetchone()
        if not task:
            continue
        status = "picked" if pqty >= task["qty"] else "short"
        db.execute(
            """UPDATE pick_tasks SET picked_qty=?, status=?, picked_by=?, picked_at=datetime('now','localtime')
               WHERE id=?""",
            (pqty, status, operator, tid)
        )
        # 扣减库存
        wave_line = db.execute("SELECT * FROM wave_lines WHERE id=?", (task["wave_line_id"],)).fetchone()
        if wave_line:
            upsert_inventory(db, sku_id=task["sku_id"], location_id=task["location_id"],
                             batch_no=wave_line["batch_no"] or "", qty_change=-pqty)
            write_transaction(db, sku_id=task["sku_id"], location_id=task["location_id"],
                              batch_no=wave_line["batch_no"] or "",
                              transaction_type="outbound", qty_change=-pqty,
                              reference_type="wave", reference_no=f"WV{wave_line['wave_id']}",
                              operator=operator, remark="拣货出库")
            update_location_load(db, task["location_id"])
            db.execute(
                "UPDATE wave_lines SET picked_qty=picked_qty+? WHERE id=?",
                (pqty, wave_line["id"])
            )
            # 更新SO行已拣量
            so_line = db.execute("SELECT * FROM so_lines WHERE id=?", (wave_line["so_line_id"],)).fetchone()
            if so_line:
                db.execute("UPDATE so_lines SET picked_qty=picked_qty+? WHERE id=?", (pqty, so_line["id"]))

    db.execute("UPDATE wave_headers SET status='picking', updated_at=datetime('now','localtime') WHERE id=?", (id,))
    db.commit()
    return RedirectResponse(f"/outbound/wave/{id}/pick", 303)


# ======================== 复核发货 ========================
@router.post("/wave/{id}/pack")
def pack_wave(id: int, operator: str = Form(""), db=Depends(get_db)):
    db.execute("UPDATE wave_headers SET status='packed', updated_at=datetime('now','localtime') WHERE id=?", (id,))
    db.commit()
    return RedirectResponse(f"/outbound/wave/{id}", 303)


@router.post("/wave/{id}/ship")
def ship_wave(id: int, operator: str = Form(""), db=Depends(get_db)):
    wave = db.execute("SELECT * FROM wave_headers WHERE id=?", (id,)).fetchone()
    if not wave:
        return RedirectResponse("/outbound", 303)

    # 关联的SO行更新发货量
    db.execute(
        """UPDATE so_lines SET shipped_qty=picked_qty
           WHERE id IN (SELECT DISTINCT so_line_id FROM wave_lines WHERE wave_id=?)""",
        (id,)
    )
    db.execute("UPDATE wave_headers SET status='shipped', updated_at=datetime('now','localtime') WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/outbound", 303)


# ======================== 快速出库 ========================
@router.get("/quick")
def quick_outbound_form(request: Request, db=Depends(get_db)):
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    skus = db.execute("SELECT * FROM skus WHERE status='active'").fetchall()
    so_types = SO_TYPES
    so_type_labels = SO_TYPE_LABELS
    return templates.TemplateResponse("outbound/quick_outbound.html", {
        "request": request, "active_page": "outbound",
        "warehouses": warehouses, "skus": skus,
        "so_types": so_types, "so_type_labels": so_type_labels,
    })
