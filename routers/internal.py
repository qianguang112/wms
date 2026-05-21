from datetime import date
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import (templates, COUNT_TYPES, COUNT_TYPE_LABELS, BLOCK_TYPES,
                         BLOCK_TYPE_LABELS, DEFAULT_EXPIRY_WARNING_DAYS)
from utils.helpers import (generate_count_plan_no, generate_move_no, safe_create,
                           write_transaction, upsert_inventory, update_location_load)

router = APIRouter(prefix="/internal")


# ======================== 总览 ========================
@router.get("")
def overview(request: Request, db=Depends(get_db)):
    pending_asn = db.execute("SELECT COUNT(*) as c FROM asn_headers WHERE status IN ('draft','receiving')").fetchone()["c"]
    pending_receipt = db.execute("SELECT COUNT(*) as c FROM receipt_headers WHERE status IN ('pending','qc_done','pending_putaway')").fetchone()["c"]
    pending_pick = db.execute("SELECT COUNT(*) as c FROM pick_tasks WHERE status='pending'").fetchone()["c"]
    pending_ship = db.execute("SELECT COUNT(*) as c FROM wave_headers WHERE status IN ('picked','packed')").fetchone()["c"]
    frozen_count = db.execute("SELECT COUNT(*) as c FROM inventory_blocks WHERE status='frozen'").fetchone()["c"]
    near_expiry = db.execute(
        "SELECT COUNT(*) as c FROM inventory WHERE expiry_date IS NOT NULL AND expiry_date <= date('now','localtime',?) AND qty > 0",
        (f"+{DEFAULT_EXPIRY_WARNING_DAYS} days",)
    ).fetchone()["c"]
    pending_count = db.execute("SELECT COUNT(*) as c FROM count_tasks WHERE status='pending'").fetchone()["c"]

    return templates.TemplateResponse("internal/overview.html", {
        "request": request, "active_page": "internal",
        "pending_asn": pending_asn, "pending_receipt": pending_receipt,
        "pending_pick": pending_pick, "pending_ship": pending_ship,
        "frozen_count": frozen_count, "near_expiry": near_expiry,
        "pending_count": pending_count,
    })


# ======================== 盘点 ========================
@router.get("/count/plan/new")
def new_count_plan_form(request: Request, db=Depends(get_db)):
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    return templates.TemplateResponse("internal/count_plan_form.html", {
        "request": request, "active_page": "internal",
        "warehouses": warehouses, "count_types": COUNT_TYPES, "count_type_labels": COUNT_TYPE_LABELS,
    })


@router.post("/count/plan/new")
def create_count_plan(warehouse_id: int = Form(...), area_id: int = Form(None),
                      count_type: str = Form("blind"), created_by: str = Form(""),
                      db=Depends(get_db)):

    def do_insert():
        plan_no = generate_count_plan_no(db)
        db.execute(
            "INSERT INTO count_plans (plan_no, warehouse_id, area_id, count_type, created_by) VALUES (?,?,?,?,?)",
            (plan_no, warehouse_id, area_id if area_id else None, count_type, created_by)
        )
        plan_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]

        # 生成盘点任务
        if count_type == "movement":
            # 动碰盘点：有出入库记录的库位
            sql = """
                SELECT DISTINCT i.sku_id, i.location_id, i.batch_no, i.qty
                FROM inventory i
                JOIN locations l ON i.location_id=l.id
                JOIN warehouse_areas a ON l.area_id=a.id
                WHERE a.warehouse_id=? AND i.qty > 0
                AND i.location_id IN (
                    SELECT DISTINCT location_id FROM inventory_transactions
                    WHERE created_at >= date('now','localtime','-7 days')
                )
            """
            rows = db.execute(sql, (warehouse_id,)).fetchall()
        elif area_id:
            rows = db.execute(
                """SELECT sku_id, location_id, batch_no, qty FROM inventory
                   WHERE location_id IN (SELECT id FROM locations WHERE area_id=?) AND qty > 0""",
                (area_id,)
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT i.sku_id, i.location_id, i.batch_no, i.qty FROM inventory i
                   JOIN locations l ON i.location_id=l.id
                   JOIN warehouse_areas a ON l.area_id=a.id
                   WHERE a.warehouse_id=? AND i.qty > 0""",
                (warehouse_id,)
            ).fetchall()

        for r in rows:
            db.execute(
                """INSERT INTO count_tasks (plan_id, location_id, sku_id, batch_no, system_qty)
                   VALUES (?,?,?,?,?)""",
                (plan_id, r["location_id"], r["sku_id"], r["batch_no"] or "", r["qty"])
            )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/internal", 303)


@router.get("/count/plan/{id}")
def count_plan_detail(id: int, request: Request, db=Depends(get_db)):
    plan = db.execute(
        """SELECT p.*, w.name as warehouse_name
           FROM count_plans p JOIN warehouses w ON p.warehouse_id=w.id WHERE p.id=?""", (id,)
    ).fetchone()
    if not plan:
        return RedirectResponse("/internal", 303)

    tasks = db.execute(
        """SELECT t.*, l.code as location_code, s.name as sku_name, s.sku_code
           FROM count_tasks t
           JOIN locations l ON t.location_id=l.id
           LEFT JOIN skus s ON t.sku_id=s.id
           WHERE t.plan_id=?
           ORDER BY l.code""",
        (id,)
    ).fetchall()

    return templates.TemplateResponse("internal/count_plan_detail.html", {
        "request": request, "active_page": "internal", "plan": plan, "tasks": tasks,
        "count_type_labels": COUNT_TYPE_LABELS,
    })


@router.get("/count/plan/{id}/execute")
def count_execute(id: int, request: Request, db=Depends(get_db)):
    plan = db.execute(
        """SELECT p.*, w.name as warehouse_name
           FROM count_plans p JOIN warehouses w ON p.warehouse_id=w.id WHERE p.id=?""", (id,)
    ).fetchone()
    if not plan:
        return RedirectResponse("/internal", 303)

    tasks = db.execute(
        """SELECT t.*, l.code as location_code, s.name as sku_name, s.sku_code, s.unit
           FROM count_tasks t
           JOIN locations l ON t.location_id=l.id
           LEFT JOIN skus s ON t.sku_id=s.id
           WHERE t.plan_id=? AND t.status='pending'
           ORDER BY l.code""",
        (id,)
    ).fetchall()

    return templates.TemplateResponse("internal/count_execute.html", {
        "request": request, "active_page": "internal", "plan": plan, "tasks": tasks,
        "count_type_labels": COUNT_TYPE_LABELS,
    })


@router.post("/count/plan/{id}/execute")
def submit_count(id: int, task_ids: list = Form(...), count_qtys: list = Form(...),
                 counted_by: str = Form(""), db=Depends(get_db)):
    for i in range(len(task_ids)):
        tid = int(task_ids[i])
        cqty = float(count_qtys[i]) if count_qtys[i] is not None and count_qtys[i] != "" else None
        task = db.execute("SELECT * FROM count_tasks WHERE id=?", (tid,)).fetchone()
        if not task:
            continue
        diff = cqty - task["system_qty"] if cqty is not None else None
        db.execute(
            """UPDATE count_tasks SET count_qty=?, difference=?, status='counted',
               counted_by=?, counted_at=datetime('now','localtime') WHERE id=?""",
            (cqty, diff, counted_by, tid)
        )
    db.commit()
    return RedirectResponse(f"/internal/count/plan/{id}", 303)


@router.post("/count/plan/{id}/complete")
def complete_count(id: int, db=Depends(get_db)):
    db.execute("UPDATE count_plans SET status='done', updated_at=datetime('now','localtime') WHERE id=?", (id,))
    db.execute("UPDATE count_tasks SET status='done' WHERE plan_id=? AND status='counted'", (id,))
    db.commit()
    return RedirectResponse(f"/internal/count/plan/{id}", 303)


@router.post("/count/plan/{id}/adjust")
def adjust_count(id: int, operator: str = Form(""), db=Depends(get_db)):
    """差异调整：对盘点差异做库存调整"""
    plan = db.execute("SELECT plan_no FROM count_plans WHERE id=?", (id,)).fetchone()
    if not plan:
        return RedirectResponse("/internal", 303)

    tasks = db.execute(
        "SELECT * FROM count_tasks WHERE plan_id=? AND difference IS NOT NULL AND difference != 0 AND status='counted'",
        (id,)
    ).fetchall()

    for t in tasks:
        diff = t["difference"]
        if diff == 0:
            continue
        # 差异调整（盘盈正数入库，盘亏负数出库）
        upsert_inventory(db, sku_id=t["sku_id"], location_id=t["location_id"],
                         batch_no=t["batch_no"] or "", qty_change=diff)
        write_transaction(db, sku_id=t["sku_id"], location_id=t["location_id"],
                          batch_no=t["batch_no"] or "",
                          transaction_type="count_adjust", qty_change=diff,
                          reference_type="count_plan", reference_no=plan["plan_no"],
                          operator=operator, remark=f"盘点调整 系统数={t['system_qty']} 实盘数={t['count_qty']}")
        update_location_load(db, t["location_id"])

    db.execute("UPDATE count_plans SET status='adjusted', updated_at=datetime('now','localtime') WHERE id=?", (id,))
    db.execute("UPDATE count_tasks SET status='done' WHERE plan_id=? AND status='counted'", (id,))
    db.commit()
    return RedirectResponse(f"/internal/count/plan/{id}", 303)


# ======================== 移库 ========================
@router.get("/move")
def move_form(request: Request, db=Depends(get_db)):
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    return templates.TemplateResponse("internal/move.html", {
        "request": request, "active_page": "internal", "warehouses": warehouses,
    })


@router.post("/move")
def do_move(sku_id: int = Form(...), from_location_id: int = Form(...),
            to_location_id: int = Form(...), batch_no: str = Form(""),
            qty: float = Form(...), moved_by: str = Form(""), remark: str = Form(""),
            db=Depends(get_db)):
    if qty <= 0 or from_location_id == to_location_id:
        return RedirectResponse("/internal/move", 303)

    def do_insert():
        move_no = generate_move_no(db)
        db.execute(
            """INSERT INTO stock_moves (move_no, sku_id, from_location_id, to_location_id, batch_no, qty, moved_by, remark)
               VALUES (?,?,?,?,?,?,?,?)""",
            (move_no, sku_id, from_location_id, to_location_id, batch_no, qty, moved_by, remark)
        )
        # 从源库位减少
        upsert_inventory(db, sku_id=sku_id, location_id=from_location_id, batch_no=batch_no, qty_change=-qty)
        write_transaction(db, sku_id=sku_id, location_id=from_location_id, batch_no=batch_no,
                          transaction_type="move", qty_change=-qty,
                          reference_type="stock_move", reference_no=move_no,
                          operator=moved_by, remark=f"移出至 {to_location_id}")
        update_location_load(db, from_location_id)

        # 到目标库位增加
        upsert_inventory(db, sku_id=sku_id, location_id=to_location_id, batch_no=batch_no, qty_change=qty)
        write_transaction(db, sku_id=sku_id, location_id=to_location_id, batch_no=batch_no,
                          transaction_type="move", qty_change=qty,
                          reference_type="stock_move", reference_no=move_no,
                          operator=moved_by, remark=f"从 {from_location_id} 移入")
        update_location_load(db, to_location_id)
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/internal", 303)


# ======================== 效期预警 ========================
@router.get("/expiry-warning")
def expiry_warning(request: Request, warning_days: int = DEFAULT_EXPIRY_WARNING_DAYS, db=Depends(get_db)):
    rows = db.execute(
        """SELECT i.*, s.name as sku_name, s.sku_code, s.unit,
                  l.code as location_code, a.name as area_name, w.name as warehouse_name
           FROM inventory i
           JOIN skus s ON i.sku_id=s.id
           JOIN locations l ON i.location_id=l.id
           JOIN warehouse_areas a ON l.area_id=a.id
           JOIN warehouses w ON a.warehouse_id=w.id
           WHERE i.expiry_date IS NOT NULL
             AND i.expiry_date <= date('now','localtime',?)
             AND i.qty > 0
           ORDER BY i.expiry_date""",
        (f"+{warning_days} days",)
    ).fetchall()
    return templates.TemplateResponse("internal/expiry_warning.html", {
        "request": request, "active_page": "internal",
        "rows": rows, "warning_days": warning_days,
    })


# ======================== 库存冻结/释放 ========================
@router.get("/block")
def block_form(request: Request, db=Depends(get_db)):
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    blocks = db.execute(
        """SELECT b.*, i.sku_id, s.name as sku_name, s.sku_code,
                  l.code as location_code
           FROM inventory_blocks b
           JOIN inventory i ON b.inventory_id=i.id
           JOIN skus s ON i.sku_id=s.id
           JOIN locations l ON i.location_id=l.id
           ORDER BY b.id DESC"""
    ).fetchall()
    return templates.TemplateResponse("internal/block.html", {
        "request": request, "active_page": "internal",
        "warehouses": warehouses, "blocks": blocks,
        "block_types": BLOCK_TYPES, "block_type_labels": BLOCK_TYPE_LABELS,
    })


@router.post("/block")
def freeze_inventory(inventory_id: int = Form(...), frozen_qty: float = Form(...),
                     block_type: str = Form("qc"), reason: str = Form(""),
                     created_by: str = Form(""), db=Depends(get_db)):
    inv = db.execute("SELECT * FROM inventory WHERE id=?", (inventory_id,)).fetchone()
    if not inv or frozen_qty <= 0:
        return RedirectResponse("/internal/block", 303)

    available = inv["qty"] - inv["frozen_qty"]
    if frozen_qty > available:
        frozen_qty = available

    db.execute(
        "INSERT INTO inventory_blocks (inventory_id, block_type, frozen_qty, reason, created_by) VALUES (?,?,?,?,?)",
        (inventory_id, block_type, frozen_qty, reason, created_by)
    )
    db.execute("UPDATE inventory SET frozen_qty=frozen_qty+?, updated_at=datetime('now','localtime') WHERE id=?",
               (frozen_qty, inventory_id))
    write_transaction(db, sku_id=inv["sku_id"], location_id=inv["location_id"],
                      batch_no=inv["batch_no"], transaction_type="freeze", qty_change=0,
                      reference_type="inventory_block", reference_no=str(inventory_id),
                      operator=created_by, remark=f"冻结 {frozen_qty} ({block_type})")
    db.commit()
    return RedirectResponse("/internal/block", 303)


@router.post("/block/{id}/release")
def release_inventory(id: int, released_by: str = Form(""), db=Depends(get_db)):
    block = db.execute("SELECT * FROM inventory_blocks WHERE id=? AND status='frozen'", (id,)).fetchone()
    if not block:
        return RedirectResponse("/internal/block", 303)

    inv = db.execute("SELECT * FROM inventory WHERE id=?", (block["inventory_id"],)).fetchone()
    db.execute(
        "UPDATE inventory_blocks SET status='released', released_qty=frozen_qty, released_by=?, released_at=datetime('now','localtime') WHERE id=?",
        (released_by, id)
    )
    db.execute("UPDATE inventory SET frozen_qty=MAX(0, frozen_qty-?), updated_at=datetime('now','localtime') WHERE id=?",
               (block["frozen_qty"], block["inventory_id"]))
    if inv:
        write_transaction(db, sku_id=inv["sku_id"], location_id=inv["location_id"],
                          batch_no=inv["batch_no"], transaction_type="release", qty_change=0,
                          reference_type="inventory_block", reference_no=str(id),
                          operator=released_by, remark=f"释放冻结 {block['frozen_qty']}")
    db.commit()
    return RedirectResponse("/internal/block", 303)
