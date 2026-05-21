from datetime import date
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates
from utils.helpers import generate_item_no, generate_inbound_no, generate_outbound_no, safe_create

router = APIRouter(prefix="/supplies")


def _get_supply(db, supply_id: int):
    return db.execute("SELECT * FROM office_supplies WHERE id=?", (supply_id,)).fetchone()


@router.get("")
def list_supplies(request: Request, search: str = "", category: str = "", db=Depends(get_db)):
    sql = "SELECT * FROM office_supplies WHERE 1=1"
    params = []
    if search:
        sql += " AND (name LIKE ? OR item_no LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if category:
        sql += " AND category=?"
        params.append(category)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    return templates.TemplateResponse("office_supplies/list.html", {
        "request": request, "active_page": "office_supplies",
        "rows": rows, "search": search, "category": category,
    })


@router.get("/new")
def new_form(request: Request):
    return templates.TemplateResponse("office_supplies/form.html", {
        "request": request, "active_page": "office_supplies", "supply": None,
    })


@router.post("/new")
def create(request: Request, name: str = Form(""), category: str = Form(""),
           spec: str = Form(""), unit: str = Form("个"), safety_qty: float = Form(0),
           remark: str = Form(""), db=Depends(get_db)):
    if not name:
        return templates.TemplateResponse("office_supplies/form.html", {
            "request": request, "active_page": "office_supplies",
            "supply": {"name": name, "category": category, "spec": spec,
                       "unit": unit, "safety_qty": safety_qty, "remark": remark},
            "error": "请填写必填字段：名称",
        })

    def do_insert():
        item_no = generate_item_no(db)
        db.execute(
            "INSERT INTO office_supplies (item_no, name, category, spec, unit, safety_qty, remark) VALUES (?,?,?,?,?,?,?)",
            (item_no, name, category, spec, unit, safety_qty, remark)
        )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/supplies", 303)


@router.get("/{id}/edit")
def edit_form(id: int, request: Request, db=Depends(get_db)):
    row = _get_supply(db, id)
    if not row:
        return RedirectResponse("/supplies", 303)
    return templates.TemplateResponse("office_supplies/form.html", {
        "request": request, "active_page": "office_supplies", "supply": row,
    })


@router.post("/{id}/edit")
def update(id: int, request: Request, name: str = Form(""), category: str = Form(""),
           spec: str = Form(""), unit: str = Form("个"), safety_qty: float = Form(0),
           remark: str = Form(""), db=Depends(get_db)):
    supply = _get_supply(db, id)
    if not supply:
        return RedirectResponse("/supplies", 303)
    if not name:
        return templates.TemplateResponse("office_supplies/form.html", {
            "request": request, "active_page": "office_supplies",
            "supply": {"id": id, "name": name, "category": category, "spec": spec,
                       "unit": unit, "safety_qty": safety_qty, "remark": remark},
            "error": "请填写必填字段：名称",
        })
    db.execute(
        """UPDATE office_supplies SET name=?, category=?, spec=?, unit=?, safety_qty=?, remark=?,
           updated_at=datetime('now','localtime') WHERE id=?""",
        (name, category, spec, unit, safety_qty, remark, id)
    )
    db.commit()
    return RedirectResponse("/supplies", 303)


@router.get("/{id}/inbound")
def inbound_form(id: int, request: Request, db=Depends(get_db)):
    supply = _get_supply(db, id)
    if not supply:
        return RedirectResponse("/supplies", 303)
    return templates.TemplateResponse("office_supplies/inbound.html", {
        "request": request, "active_page": "office_supplies", "supply": supply,
    })


@router.post("/{id}/inbound")
def inbound(id: int, request: Request, qty: float = Form(None),
            unit_price: float = Form(0), supplier: str = Form(""),
            inbound_date: str = Form(""), remark: str = Form(""), db=Depends(get_db)):
    supply = _get_supply(db, id)
    if not supply:
        return RedirectResponse("/supplies", 303)
    if qty is None or qty <= 0:
        return templates.TemplateResponse("office_supplies/inbound.html", {
            "request": request, "active_page": "office_supplies", "supply": supply,
            "error": "请填写有效的入库数量",
        })

    def do_insert():
        inbound_no = generate_inbound_no(db)
        db.execute(
            "INSERT INTO supply_inbound (inbound_no, supply_id, qty, unit_price, supplier, inbound_date, remark) VALUES (?,?,?,?,?,?,?)",
            (inbound_no, id, qty, unit_price, supplier, inbound_date or str(date.today()), remark)
        )
        db.execute(
            "UPDATE office_supplies SET current_qty=current_qty+?, updated_at=datetime('now','localtime') WHERE id=?",
            (qty, id)
        )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse(f"/supplies/{id}/history", 303)


@router.get("/{id}/outbound")
def outbound_form(id: int, request: Request, db=Depends(get_db)):
    supply = _get_supply(db, id)
    if not supply:
        return RedirectResponse("/supplies", 303)
    return templates.TemplateResponse("office_supplies/outbound.html", {
        "request": request, "active_page": "office_supplies", "supply": supply,
    })


@router.post("/{id}/outbound")
def outbound(id: int, request: Request, qty: float = Form(None),
             receiver: str = Form(""), department: str = Form(""),
             purpose: str = Form(""), outbound_date: str = Form(""),
             remark: str = Form(""), db=Depends(get_db)):
    supply = _get_supply(db, id)
    if not supply:
        return RedirectResponse("/supplies", 303)
    if qty is None or qty <= 0 or not receiver:
        return templates.TemplateResponse("office_supplies/outbound.html", {
            "request": request, "active_page": "office_supplies", "supply": supply,
            "error": "请填写必填字段：数量、领用人",
        })

    def do_insert():
        outbound_no = generate_outbound_no(db)
        db.execute(
            "INSERT INTO supply_outbound (outbound_no, supply_id, qty, receiver, department, purpose, outbound_date, remark) VALUES (?,?,?,?,?,?,?,?)",
            (outbound_no, id, qty, receiver, department, purpose, outbound_date or str(date.today()), remark)
        )
        result = db.execute(
            "UPDATE office_supplies SET current_qty=current_qty-?, updated_at=datetime('now','localtime') WHERE id=? AND current_qty>=?",
            (qty, id, qty)
        )
        if result.rowcount == 0:
            raise ValueError("库存不足")
        db.commit()

    try:
        safe_create(db, do_insert)
    except ValueError:
        return RedirectResponse(f"/supplies/{id}/outbound", 303)

    return RedirectResponse(f"/supplies/{id}/history", 303)


@router.post("/{id}/delete")
def delete(id: int, db=Depends(get_db)):
    db.execute("DELETE FROM supply_inbound WHERE supply_id=?", (id,))
    db.execute("DELETE FROM supply_outbound WHERE supply_id=?", (id,))
    db.execute("DELETE FROM office_supplies WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/supplies", 303)


@router.get("/{id}/history")
def history(id: int, request: Request, db=Depends(get_db)):
    supply = _get_supply(db, id)
    if not supply:
        return RedirectResponse("/supplies", 303)
    inbound_rows = db.execute(
        "SELECT * FROM supply_inbound WHERE supply_id=? ORDER BY id DESC", (id,)
    ).fetchall()
    outbound_rows = db.execute(
        "SELECT * FROM supply_outbound WHERE supply_id=? ORDER BY id DESC", (id,)
    ).fetchall()
    return templates.TemplateResponse("office_supplies/history.html", {
        "request": request, "active_page": "office_supplies",
        "supply": supply, "inbound_rows": inbound_rows, "outbound_rows": outbound_rows,
    })
