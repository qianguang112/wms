from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates, ASSET_STATUS_IN_USE, ASSET_STATUS_SCRAPPED, ASSET_STATUSES, ASSET_STATUS_LABELS
from utils.helpers import generate_asset_no, safe_create

router = APIRouter(prefix="/assets")


def _get_asset(db, asset_id: int):
    return db.execute("SELECT * FROM fixed_assets WHERE id=?", (asset_id,)).fetchone()


@router.get("")
def list_assets(request: Request, search: str = "", location: str = "", status: str = "", db=Depends(get_db)):
    sql = "SELECT * FROM fixed_assets WHERE 1=1"
    params = []
    if search:
        sql += " AND (name LIKE ? OR asset_no LIKE ? OR manager LIKE ? OR department LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like, like])
    if location:
        sql += " AND location LIKE ?"
        params.append(f"%{location}%")
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    return templates.TemplateResponse("fixed_assets/list.html", {
        "request": request, "active_page": "fixed_assets",
        "rows": rows, "search": search, "location": location, "status": status,
        "status_labels": ASSET_STATUS_LABELS, "scrapped_status": ASSET_STATUS_SCRAPPED,
    })


@router.get("/new")
def new_form(request: Request):
    return templates.TemplateResponse("fixed_assets/form.html", {
        "request": request, "active_page": "fixed_assets", "asset": None,
        "statuses": ASSET_STATUSES, "status_labels": ASSET_STATUS_LABELS,
    })


@router.post("/new")
def create(request: Request, name: str = Form(""), category: str = Form(""),
           spec: str = Form(""), qty: int = Form(1), unit_price: float = Form(0),
           purchase_date: str = Form(""),
           department: str = Form(""), location: str = Form(""),
           manager: str = Form(""), status: str = Form(ASSET_STATUS_IN_USE),
           remark: str = Form(""), db=Depends(get_db)):
    if not name or not manager:
        return templates.TemplateResponse("fixed_assets/form.html", {
            "request": request, "active_page": "fixed_assets",
            "asset": {
                "name": name, "category": category, "spec": spec, "qty": qty,
                "unit_price": unit_price, "purchase_date": purchase_date,
                "department": department, "location": location, "manager": manager,
                "status": status, "remark": remark,
            },
            "statuses": ASSET_STATUSES, "status_labels": ASSET_STATUS_LABELS,
            "error": "请填写必填字段：名称、管理人",
        })
    total_value = qty * unit_price

    def do_insert():
        asset_no = generate_asset_no(db)
        db.execute(
            """INSERT INTO fixed_assets (asset_no, name, category, spec, qty, unit_price, total_value,
               purchase_date, department, location, manager, status, remark)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (asset_no, name, category, spec, qty, unit_price, total_value,
             purchase_date or None, department, location, manager, status, remark)
        )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/assets", 303)


@router.get("/{id}")
def detail(id: int, request: Request, db=Depends(get_db)):
    asset = _get_asset(db, id)
    if not asset:
        return RedirectResponse("/assets", 303)
    return templates.TemplateResponse("fixed_assets/form.html", {
        "request": request, "active_page": "fixed_assets", "asset": asset, "readonly": True,
        "statuses": ASSET_STATUSES, "status_labels": ASSET_STATUS_LABELS,
    })


@router.get("/{id}/edit")
def edit_form(id: int, request: Request, db=Depends(get_db)):
    asset = _get_asset(db, id)
    if not asset:
        return RedirectResponse("/assets", 303)
    return templates.TemplateResponse("fixed_assets/form.html", {
        "request": request, "active_page": "fixed_assets", "asset": asset,
        "statuses": ASSET_STATUSES, "status_labels": ASSET_STATUS_LABELS,
    })


@router.post("/{id}/edit")
def update(id: int, request: Request, name: str = Form(""), category: str = Form(""),
           spec: str = Form(""), qty: int = Form(1), unit_price: float = Form(0),
           purchase_date: str = Form(""),
           department: str = Form(""), location: str = Form(""),
           manager: str = Form(""), status: str = Form(ASSET_STATUS_IN_USE),
           remark: str = Form(""), db=Depends(get_db)):
    asset = _get_asset(db, id)
    if not asset:
        return RedirectResponse("/assets", 303)
    if not name or not manager:
        return templates.TemplateResponse("fixed_assets/form.html", {
            "request": request, "active_page": "fixed_assets",
            "asset": {"id": id, "name": name, "category": category, "spec": spec,
                      "qty": qty, "unit_price": unit_price, "purchase_date": purchase_date,
                      "department": department, "location": location, "manager": manager,
                      "status": status, "remark": remark},
            "statuses": ASSET_STATUSES, "status_labels": ASSET_STATUS_LABELS,
            "error": "请填写必填字段：名称、管理人",
        })
    total_value = qty * unit_price
    db.execute(
        """UPDATE fixed_assets SET name=?, category=?, spec=?, qty=?, unit_price=?, total_value=?,
           purchase_date=?, department=?, location=?, manager=?, status=?, remark=?,
           updated_at=datetime('now','localtime') WHERE id=?""",
        (name, category, spec, qty, unit_price, total_value,
         purchase_date or None, department, location, manager, status, remark, id)
    )
    db.commit()
    return RedirectResponse("/assets", 303)


@router.post("/{id}/scrap")
def scrap(id: int, db=Depends(get_db)):
    asset = _get_asset(db, id)
    if not asset:
        return RedirectResponse("/assets", 303)
    db.execute(
        "UPDATE fixed_assets SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
        (ASSET_STATUS_SCRAPPED, id)
    )
    db.commit()
    return RedirectResponse("/assets", 303)


@router.post("/{id}/delete")
def delete(id: int, db=Depends(get_db)):
    asset = _get_asset(db, id)
    if not asset:
        return RedirectResponse("/assets", 303)
    db.execute("DELETE FROM fixed_assets WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/assets", 303)
