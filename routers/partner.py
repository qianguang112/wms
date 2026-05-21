from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates, PARTNER_TYPES, PARTNER_TYPE_LABELS
from utils.helpers import generate_partner_code, safe_create

router = APIRouter(prefix="/partner")


@router.get("")
def list_partners(request: Request, search: str = "", partner_type: str = "", db=Depends(get_db)):
    sql = "SELECT * FROM partners WHERE 1=1"
    params = []
    if search:
        sql += " AND (name LIKE ? OR code LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if partner_type:
        sql += " AND partner_type=?"
        params.append(partner_type)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    return templates.TemplateResponse("partner/list.html", {
        "request": request, "active_page": "partner",
        "rows": rows, "search": search, "partner_type": partner_type,
        "partner_types": PARTNER_TYPES, "partner_type_labels": PARTNER_TYPE_LABELS,
    })


@router.get("/new")
def new_form(request: Request):
    return templates.TemplateResponse("partner/form.html", {
        "request": request, "active_page": "partner", "partner": None,
        "partner_types": PARTNER_TYPES, "partner_type_labels": PARTNER_TYPE_LABELS,
    })


@router.post("/new")
def create(request: Request, name: str = Form(""), partner_type: str = Form("supplier"),
           contact_person: str = Form(""), contact_phone: str = Form(""), address: str = Form(""),
           remark: str = Form(""), db=Depends(get_db)):
    if not name:
        return templates.TemplateResponse("partner/form.html", {
            "request": request, "active_page": "partner", "partner": None,
            "partner_types": PARTNER_TYPES, "partner_type_labels": PARTNER_TYPE_LABELS,
            "error": "请填写必填字段：单位名称",
        })

    def do_insert():
        code = generate_partner_code(db)
        db.execute(
            """INSERT INTO partners (code, name, partner_type, contact_person, contact_phone, address, remark)
               VALUES (?,?,?,?,?,?,?)""",
            (code, name, partner_type, contact_person, contact_phone, address, remark)
        )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/partner", 303)


@router.get("/{id}/edit")
def edit_form(id: int, request: Request, db=Depends(get_db)):
    p = db.execute("SELECT * FROM partners WHERE id=?", (id,)).fetchone()
    if not p:
        return RedirectResponse("/partner", 303)
    return templates.TemplateResponse("partner/form.html", {
        "request": request, "active_page": "partner", "partner": p,
        "partner_types": PARTNER_TYPES, "partner_type_labels": PARTNER_TYPE_LABELS,
    })


@router.post("/{id}/edit")
def update(id: int, request: Request, name: str = Form(""), partner_type: str = Form("supplier"),
           contact_person: str = Form(""), contact_phone: str = Form(""), address: str = Form(""),
           remark: str = Form(""), db=Depends(get_db)):
    p = db.execute("SELECT * FROM partners WHERE id=?", (id,)).fetchone()
    if not p:
        return RedirectResponse("/partner", 303)
    if not name:
        return templates.TemplateResponse("partner/form.html", {
            "request": request, "active_page": "partner",
            "partner": {"id": id, "name": name, "partner_type": partner_type,
                        "contact_person": contact_person, "contact_phone": contact_phone,
                        "address": address, "remark": remark},
            "partner_types": PARTNER_TYPES, "partner_type_labels": PARTNER_TYPE_LABELS,
            "error": "请填写必填字段：单位名称",
        })
    db.execute(
        """UPDATE partners SET name=?, partner_type=?, contact_person=?, contact_phone=?, address=?, remark=?,
           updated_at=datetime('now','localtime') WHERE id=?""",
        (name, partner_type, contact_person, contact_phone, address, remark, id)
    )
    db.commit()
    return RedirectResponse("/partner", 303)


@router.post("/{id}/delete")
def delete(id: int, db=Depends(get_db)):
    db.execute("DELETE FROM partners WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/partner", 303)
