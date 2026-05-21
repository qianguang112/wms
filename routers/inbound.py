from datetime import date
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import (templates, RECEIPT_TYPES, RECEIPT_TYPE_LABELS,
                         RECEIPT_STATUS_LABELS, RECEIPT_STATUS_PENDING, RECEIPT_STATUS_QC_DONE,
                         RECEIPT_STATUS_PENDING_PUTAWAY, RECEIPT_STATUS_CONFIRMED,
                         AREA_TYPE_LABELS, LOCATION_STATUS_EMPTY, LOCATION_STATUS_OCCUPIED)
from utils.helpers import (generate_asn_no, generate_receipt_no, safe_create,
                           calc_expiry_date, write_transaction, upsert_inventory, update_location_load)

router = APIRouter(prefix="/inbound")


def _get_putaway_recommendation(db, sku_id: int, warehouse_id: int):
    """上架推荐：同品相邻 > ABC分类优先区 > 任意空库位"""
    # 1. 查找该SKU在其他库位是否有存放（同品相邻原则）
    existing_loc = db.execute(
        """SELECT l.* FROM locations l
           JOIN inventory i ON i.location_id = l.id
           JOIN warehouse_areas a ON a.id = l.area_id
           WHERE i.sku_id=? AND a.warehouse_id=? AND l.status='occupied'
           AND (l.capacity IS NULL OR l.current_load < l.capacity)
           ORDER BY l.code LIMIT 1""",
        (sku_id, warehouse_id)
    ).fetchone()
    if existing_loc:
        return existing_loc

    # 2. 按ABC分类推荐
    sku = db.execute("SELECT abc_class FROM skus WHERE id=?", (sku_id,)).fetchone()
    if sku and sku["abc_class"] == "A":
        # A类：优先仓库前半区（编码小的区域）
        area = db.execute(
            """SELECT a.id FROM warehouse_areas a
               WHERE a.warehouse_id=? AND a.status='active' ORDER BY a.code LIMIT 1""",
            (warehouse_id,)
        ).fetchone()
        if area:
            loc = db.execute(
                """SELECT * FROM locations WHERE area_id=? AND status='empty'
                   ORDER BY code LIMIT 1""",
                (area["id"],)
            ).fetchone()
            if loc:
                return loc

    # 3. 任意空库位
    loc = db.execute(
        """SELECT l.* FROM locations l
           JOIN warehouse_areas a ON a.id = l.area_id
           WHERE a.warehouse_id=? AND l.status='empty'
           ORDER BY l.code LIMIT 1""",
        (warehouse_id,)
    ).fetchone()
    return loc


# ======================== 入库列表 ========================
@router.get("")
def list_inbound(request: Request, type: str = "", status: str = "", db=Depends(get_db)):
    # 收货单
    sql = "SELECT r.*, w.name as warehouse_name FROM receipt_headers r JOIN warehouses w ON r.warehouse_id=w.id WHERE 1=1"
    params = []
    if type:
        sql += " AND r.receipt_type=?"
        params.append(type)
    if status:
        sql += " AND r.status=?"
        params.append(status)
    sql += " ORDER BY r.id DESC"
    receipts = db.execute(sql, params).fetchall()
    # ASN
    asns = db.execute(
        """SELECT a.*, w.name as warehouse_name, p.name as partner_name
           FROM asn_headers a
           JOIN warehouses w ON a.warehouse_id=w.id
           JOIN partners p ON a.partner_id=p.id
           ORDER BY a.id DESC"""
    ).fetchall()
    return templates.TemplateResponse("inbound/list.html", {
        "request": request, "active_page": "inbound",
        "receipts": receipts, "asns": asns, "type": type, "status": status,
        "receipt_types": RECEIPT_TYPES, "receipt_type_labels": RECEIPT_TYPE_LABELS,
        "receipt_status_labels": RECEIPT_STATUS_LABELS,
        "S": {"PENDING": RECEIPT_STATUS_PENDING, "QC_DONE": RECEIPT_STATUS_QC_DONE,
              "PENDING_PUTAWAY": RECEIPT_STATUS_PENDING_PUTAWAY, "CONFIRMED": RECEIPT_STATUS_CONFIRMED},
    })


# ======================== ASN ========================
@router.get("/asn/new")
def new_asn_form(request: Request, db=Depends(get_db)):
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    partners = db.execute("SELECT * FROM partners WHERE partner_type IN ('supplier','both') AND status='active'").fetchall()
    skus = db.execute("SELECT * FROM skus WHERE status='active'").fetchall()
    return templates.TemplateResponse("inbound/asn_form.html", {
        "request": request, "active_page": "inbound",
        "warehouses": warehouses, "partners": partners, "skus": skus,
    })


@router.post("/asn/new")
def create_asn(warehouse_id: int = Form(...), partner_id: int = Form(...),
               asn_type: str = Form("purchase"), expected_date: str = Form(""),
               remark: str = Form(""), created_by: str = Form(""),
               sku_ids: list = Form(...), expected_qtys: list = Form(...),
               batch_nos: list = Form(None), production_dates: list = Form(None),
               db=Depends(get_db)):

    def do_insert():
        asn_no = generate_asn_no(db)
        db.execute(
            """INSERT INTO asn_headers (asn_no, partner_id, warehouse_id, asn_type, expected_date, remark, created_by)
               VALUES (?,?,?,?,?,?,?)""",
            (asn_no, partner_id, warehouse_id, asn_type, expected_date or None, remark, created_by)
        )
        asn_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]

        for i in range(len(sku_ids)):
            sku_id = int(sku_ids[i])
            qty = float(expected_qtys[i])
            batch = batch_nos[i] if batch_nos and i < len(batch_nos) and batch_nos[i] else ""
            prod_date = production_dates[i] if production_dates and i < len(production_dates) and production_dates[i] else None
            sku = db.execute("SELECT shelf_life_days FROM skus WHERE id=?", (sku_id,)).fetchone()
            exp_date = calc_expiry_date(prod_date, sku["shelf_life_days"]) if sku and prod_date else None
            db.execute(
                """INSERT INTO asn_lines (asn_id, line_no, sku_id, expected_qty, batch_no, production_date, expiry_date)
                   VALUES (?,?,?,?,?,?,?)""",
                (asn_id, i + 1, sku_id, qty, batch, prod_date, exp_date)
            )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/inbound", 303)


@router.get("/asn/{id}")
def asn_detail(id: int, request: Request, db=Depends(get_db)):
    asn = db.execute(
        """SELECT h.*, w.name as warehouse_name, p.name as partner_name
           FROM asn_headers h JOIN warehouses w ON h.warehouse_id=w.id JOIN partners p ON h.partner_id=p.id
           WHERE h.id=?""", (id,)
    ).fetchone()
    if not asn:
        return RedirectResponse("/inbound", 303)
    lines = db.execute(
        """SELECT l.*, s.name as sku_name, s.sku_code, s.unit
           FROM asn_lines l JOIN skus s ON l.sku_id=s.id WHERE l.asn_id=?""", (id,)
    ).fetchall()
    return templates.TemplateResponse("inbound/asn_detail.html", {
        "request": request, "active_page": "inbound", "asn": asn, "lines": lines,
    })


@router.post("/asn/{id}/delete")
def delete_asn(id: int, db=Depends(get_db)):
    db.execute("DELETE FROM asn_lines WHERE asn_id=?", (id,))
    db.execute("DELETE FROM asn_headers WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/inbound", 303)


# ======================== 收货 ========================
@router.post("/asn/{id}/receive")
def create_receipt_from_asn(id: int, receipt_type: str = Form("purchase"), created_by: str = Form(""), db=Depends(get_db)):
    asn = db.execute("SELECT * FROM asn_headers WHERE id=?", (id,)).fetchone()
    if not asn:
        return RedirectResponse("/inbound", 303)

    def do_insert():
        receipt_no = generate_receipt_no(db)
        db.execute(
            """INSERT INTO receipt_headers (receipt_no, asn_id, warehouse_id, receipt_type, created_by)
               VALUES (?,?,?,?,?)""",
            (receipt_no, id, asn["warehouse_id"], receipt_type, created_by)
        )
        receipt_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]

        asn_lines = db.execute("SELECT * FROM asn_lines WHERE asn_id=?", (id,)).fetchall()
        for i, line in enumerate(asn_lines):
            db.execute(
                """INSERT INTO receipt_lines (receipt_id, line_no, sku_id, received_qty, accepted_qty,
                   batch_no, production_date, expiry_date)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (receipt_id, i + 1, line["sku_id"], line["expected_qty"], line["expected_qty"],
                 line["batch_no"], line["production_date"], line["expiry_date"])
            )
        # 更新ASN状态
        db.execute("UPDATE asn_headers SET status='received', updated_at=datetime('now','localtime') WHERE id=?", (id,))
        db.execute("UPDATE asn_lines SET received_qty=expected_qty WHERE asn_id=?", (id,))
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse(f"/inbound", 303)


@router.get("/receipt/{id}")
def receipt_detail(id: int, request: Request, db=Depends(get_db)):
    receipt = db.execute(
        """SELECT r.*, w.name as warehouse_name
           FROM receipt_headers r JOIN warehouses w ON r.warehouse_id=w.id WHERE r.id=?""", (id,)
    ).fetchone()
    if not receipt:
        return RedirectResponse("/inbound", 303)
    lines = db.execute(
        """SELECT l.*, s.name as sku_name, s.sku_code, s.unit
           FROM receipt_lines l JOIN skus s ON l.sku_id=s.id WHERE l.receipt_id=?""", (id,)
    ).fetchall()
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    return templates.TemplateResponse("inbound/receipt_detail.html", {
        "request": request, "active_page": "inbound", "receipt": receipt, "lines": lines,
        "receipt_types": RECEIPT_TYPES, "receipt_type_labels": RECEIPT_TYPE_LABELS,
        "receipt_status_labels": RECEIPT_STATUS_LABELS,
        "S": {"PENDING": RECEIPT_STATUS_PENDING, "QC_DONE": RECEIPT_STATUS_QC_DONE,
              "PENDING_PUTAWAY": RECEIPT_STATUS_PENDING_PUTAWAY, "CONFIRMED": RECEIPT_STATUS_CONFIRMED},
    })


@router.post("/receipt/{id}/qc")
def qc_receipt(id: int, line_ids: list = Form(...), accepted_qtys: list = Form(...),
               rejected_qtys: list = Form(...), qc_results: list = Form(...),
               qc_remarks: list = Form(None), qc_inspector: str = Form(""), db=Depends(get_db)):
    for i in range(len(line_ids)):
        lid = int(line_ids[i])
        accepted = float(accepted_qtys[i]) if accepted_qtys[i] else 0
        rejected = float(rejected_qtys[i]) if rejected_qtys[i] else 0
        result = qc_results[i]
        remark = qc_remarks[i] if qc_remarks and i < len(qc_remarks) else ""
        db.execute(
            """UPDATE receipt_lines SET accepted_qty=?, rejected_qty=?, qc_result=?, qc_remark=?
               WHERE id=?""",
            (accepted, rejected, result, remark, lid)
        )
    db.execute(
        "UPDATE receipt_headers SET status=?, qc_inspector=?, updated_at=datetime('now','localtime') WHERE id=?",
        (RECEIPT_STATUS_QC_DONE, qc_inspector or None, id)
    )
    db.commit()
    return RedirectResponse(f"/inbound/receipt/{id}", 303)


@router.post("/receipt/{id}/release")
def release_for_putaway(id: int, db=Depends(get_db)):
    result = db.execute(
        "UPDATE receipt_headers SET status=?, updated_at=datetime('now','localtime') WHERE id=? AND status=?",
        (RECEIPT_STATUS_PENDING_PUTAWAY, id, RECEIPT_STATUS_QC_DONE)
    )
    if result.rowcount == 0:
        return RedirectResponse("/inbound", 303)
    db.commit()
    return RedirectResponse(f"/inbound/receipt/{id}", 303)


@router.post("/receipt/{id}/delete")
def delete_receipt(id: int, db=Depends(get_db)):
    receipt = db.execute("SELECT * FROM receipt_headers WHERE id=?", (id,)).fetchone()
    if not receipt:
        return RedirectResponse("/inbound", 303)
    db.execute("DELETE FROM putaway_tasks WHERE receipt_line_id IN (SELECT id FROM receipt_lines WHERE receipt_id=?)", (id,))
    db.execute("DELETE FROM receipt_lines WHERE receipt_id=?", (id,))
    db.execute("DELETE FROM receipt_headers WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/inbound", 303)


# ======================== 上架 ========================
@router.get("/receipt/{id}/putaway")
def putaway_page(id: int, request: Request, db=Depends(get_db)):
    receipt = db.execute(
        """SELECT r.*, w.name as warehouse_name, w.id as wh_id
           FROM receipt_headers r JOIN warehouses w ON r.warehouse_id=w.id WHERE r.id=? AND r.status=?""",
        (id, RECEIPT_STATUS_PENDING_PUTAWAY)
    ).fetchone()
    if not receipt:
        return RedirectResponse("/inbound", 303)
    lines = db.execute(
        """SELECT l.*, s.name as sku_name, s.sku_code
           FROM receipt_lines l JOIN skus s ON l.sku_id=s.id WHERE l.receipt_id=? AND l.accepted_qty>0""",
        (id,)
    ).fetchall()

    # 为每行生成推荐库位
    recommendations = []
    for line in lines:
        rec_loc = _get_putaway_recommendation(db, line["sku_id"], receipt["wh_id"])
        recommendations.append({
            "line": line,
            "recommended": rec_loc,
            "area_name": None,
        })
        if rec_loc:
            area = db.execute("SELECT * FROM warehouse_areas WHERE id=?", (rec_loc["area_id"],)).fetchone()
            if area:
                recommendations[-1]["area_name"] = area["name"]

    return templates.TemplateResponse("inbound/putaway.html", {
        "request": request, "active_page": "inbound", "receipt": receipt,
        "recommendations": recommendations,
    })


@router.post("/receipt/{id}/putaway/confirm")
def confirm_putaway(id: int, line_ids: list = Form(...), location_ids: list = Form(...),
                    qtys: list = Form(...), operator: str = Form(""), db=Depends(get_db)):
    receipt = db.execute(
        "SELECT r.*, r.receipt_type as rtype FROM receipt_headers r WHERE r.id=?", (id,)
    ).fetchone()
    if not receipt:
        return RedirectResponse("/inbound", 303)

    for i in range(len(line_ids)):
        lid = int(line_ids[i])
        loc_id = int(location_ids[i])
        qty = float(qtys[i])

        line = db.execute("SELECT * FROM receipt_lines WHERE id=?", (lid,)).fetchone()
        if not line or qty <= 0:
            continue

        # 写入/更新库存
        upsert_inventory(db, sku_id=line["sku_id"], location_id=loc_id,
                         batch_no=line["batch_no"] or "", qty_change=qty)

        # 写入库存流水
        write_transaction(db, sku_id=line["sku_id"], location_id=loc_id,
                          batch_no=line["batch_no"] or "",
                          transaction_type="inbound", qty_change=qty,
                          reference_type="receipt", reference_no=receipt["receipt_no"],
                          reference_line_id=lid, operator=operator,
                          remark=f"{receipt['rtype']}入库")

        # 更新库位负载
        update_location_load(db, loc_id)

        # 标记上架任务完成
        db.execute(
            "UPDATE putaway_tasks SET status='completed', completed_by=?, completed_at=datetime('now','localtime') WHERE receipt_line_id=?",
            (operator, lid)
        )

    db.execute("UPDATE receipt_headers SET status=?, updated_at=datetime('now','localtime') WHERE id=?", (RECEIPT_STATUS_CONFIRMED, id))
    db.commit()
    return RedirectResponse("/inbound", 303)


# ======================== 其他入库快捷入口 ========================
@router.get("/quick")
def quick_inbound_form(request: Request, db=Depends(get_db)):
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    skus = db.execute("SELECT * FROM skus WHERE status='active'").fetchall()
    locations = db.execute(
        "SELECT l.*, a.name as area_name FROM locations l JOIN warehouse_areas a ON l.area_id=a.id WHERE l.status!='frozen' ORDER BY a.name, l.code"
    ).fetchall()
    return templates.TemplateResponse("inbound/quick_inbound.html", {
        "request": request, "active_page": "inbound",
        "warehouses": warehouses, "skus": skus, "locations": locations,
        "receipt_types": RECEIPT_TYPES, "receipt_type_labels": RECEIPT_TYPE_LABELS,
    })


@router.post("/quick")
def quick_inbound(request: Request, warehouse_id: int = Form(None), receipt_type: str = Form("purchase"),
                  sku_id: int = Form(None), qty: float = Form(None), location_id: int = Form(None),
                  batch_no: str = Form(""), production_date: str = Form(""),
                  operator: str = Form(""), remark: str = Form(""), db=Depends(get_db)):
    # 重新获取下拉数据
    warehouses = db.execute("SELECT * FROM warehouses WHERE status='active'").fetchall()
    skus = db.execute("SELECT * FROM skus WHERE status='active'").fetchall()
    locations = db.execute(
        "SELECT l.*, a.name as area_name FROM locations l JOIN warehouse_areas a ON l.area_id=a.id WHERE l.status!='frozen' ORDER BY a.name, l.code"
    ).fetchall()
    ctx = {
        "request": request, "active_page": "inbound",
        "warehouses": warehouses, "skus": skus, "locations": locations,
        "receipt_types": RECEIPT_TYPES, "receipt_type_labels": RECEIPT_TYPE_LABELS,
    }

    if not warehouse_id or not sku_id or qty is None or not location_id:
        ctx["error"] = "请填写所有必填字段"
        return templates.TemplateResponse("inbound/quick_inbound.html", ctx)
    if qty <= 0:
        ctx["error"] = "数量必须大于0"
        return templates.TemplateResponse("inbound/quick_inbound.html", ctx)

    warehouse = db.execute("SELECT id FROM warehouses WHERE id=?", (warehouse_id,)).fetchone()
    if not warehouse:
        ctx["error"] = "所选仓库不存在"
        return templates.TemplateResponse("inbound/quick_inbound.html", ctx)

    sku = db.execute("SELECT id, shelf_life_days FROM skus WHERE id=?", (sku_id,)).fetchone()
    if not sku:
        ctx["error"] = "所选物料不存在"
        return templates.TemplateResponse("inbound/quick_inbound.html", ctx)

    loc = db.execute("SELECT id FROM locations WHERE id=?", (location_id,)).fetchone()
    if not loc:
        ctx["error"] = "所选库位不存在，请先创建库位"
        return templates.TemplateResponse("inbound/quick_inbound.html", ctx)

    expiry_date = calc_expiry_date(production_date, sku["shelf_life_days"]) if production_date else None

    def do_insert():
        receipt_no = generate_receipt_no(db)
        db.execute(
            "INSERT INTO receipt_headers (receipt_no, warehouse_id, receipt_type, status, created_by, remark) VALUES (?,?,?,?,?,?)",
            (receipt_no, warehouse_id, receipt_type, RECEIPT_STATUS_PENDING, operator, remark)
        )
        receipt_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        db.execute(
            """INSERT INTO receipt_lines (receipt_id, line_no, sku_id, received_qty, accepted_qty, batch_no, production_date, expiry_date, qc_result)
               VALUES (?,1,?,?,?,?,?,?,'pass')""",
            (receipt_id, sku_id, qty, qty, batch_no, production_date or None, expiry_date)
        )
        # 直接上架
        upsert_inventory(db, sku_id=sku_id, location_id=location_id, batch_no=batch_no, qty_change=qty)
        write_transaction(db, sku_id=sku_id, location_id=location_id, batch_no=batch_no,
                          transaction_type="inbound", qty_change=qty,
                          reference_type="receipt", reference_no=receipt_no,
                          operator=operator, remark=f"{receipt_type}入库")
        update_location_load(db, location_id)
        db.execute("UPDATE receipt_headers SET status=?, updated_at=datetime('now','localtime') WHERE id=?", (RECEIPT_STATUS_CONFIRMED, receipt_id))
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/inbound", 303)
