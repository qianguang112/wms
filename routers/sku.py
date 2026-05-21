from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates, ABC_CLASSES
from utils.helpers import generate_sku_code, safe_create

router = APIRouter(prefix="/sku")


@router.get("")
def list_skus(request: Request, search: str = "", category: str = "", abc_class: str = "", db=Depends(get_db)):
    sql = "SELECT * FROM skus WHERE 1=1"
    params = []
    if search:
        sql += " AND (name LIKE ? OR sku_code LIKE ? OR barcode LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if category:
        sql += " AND category=?"
        params.append(category)
    if abc_class:
        sql += " AND abc_class=?"
        params.append(abc_class)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    return templates.TemplateResponse("sku/list.html", {
        "request": request, "active_page": "sku",
        "rows": rows, "search": search, "category": category, "abc_class": abc_class,
        "abc_classes": ABC_CLASSES,
    })


@router.get("/new")
def new_form(request: Request):
    return templates.TemplateResponse("sku/form.html", {
        "request": request, "active_page": "sku", "sku": None, "abc_classes": ABC_CLASSES,
    })


@router.post("/new")
def create(request: Request, name: str = Form(""), category: str = Form(""), spec: str = Form(""),
           unit: str = Form("件"), barcode: str = Form(""), shelf_life_days: str = Form(""),
           abc_class: str = Form("C"), safety_stock: float = Form(0), max_stock: float = Form(0),
           remark: str = Form(""), db=Depends(get_db)):
    if not name:
        return templates.TemplateResponse("sku/form.html", {
            "request": request, "active_page": "sku", "sku": None, "abc_classes": ABC_CLASSES,
            "error": "请填写必填字段：SKU名称",
        })
    shelf_life = int(shelf_life_days) if shelf_life_days.strip() else None

    def do_insert():
        code = generate_sku_code(db)
        db.execute(
            """INSERT INTO skus (sku_code, name, category, spec, unit, barcode, shelf_life_days, abc_class, safety_stock, max_stock, remark)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (code, name, category, spec, unit, barcode, shelf_life, abc_class, safety_stock, max_stock, remark)
        )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/sku", 303)


@router.get("/{id}/edit")
def edit_form(id: int, request: Request, db=Depends(get_db)):
    sku = db.execute("SELECT * FROM skus WHERE id=?", (id,)).fetchone()
    if not sku:
        return RedirectResponse("/sku", 303)
    return templates.TemplateResponse("sku/form.html", {
        "request": request, "active_page": "sku", "sku": sku, "abc_classes": ABC_CLASSES,
    })


@router.post("/{id}/edit")
def update(id: int, request: Request, name: str = Form(""), category: str = Form(""), spec: str = Form(""),
           unit: str = Form("件"), barcode: str = Form(""), shelf_life_days: str = Form(""),
           abc_class: str = Form("C"), safety_stock: float = Form(0), max_stock: float = Form(0),
           remark: str = Form(""), db=Depends(get_db)):
    sku = db.execute("SELECT * FROM skus WHERE id=?", (id,)).fetchone()
    if not sku:
        return RedirectResponse("/sku", 303)
    if not name:
        return templates.TemplateResponse("sku/form.html", {
            "request": request, "active_page": "sku",
            "sku": {"id": id, "name": name, "category": category, "spec": spec, "unit": unit,
                    "barcode": barcode, "shelf_life_days": shelf_life_days, "abc_class": abc_class,
                    "safety_stock": safety_stock, "max_stock": max_stock, "remark": remark},
            "abc_classes": ABC_CLASSES,
            "error": "请填写必填字段：SKU名称",
        })
    shelf_life = int(shelf_life_days) if shelf_life_days.strip() else None
    db.execute(
        """UPDATE skus SET name=?, category=?, spec=?, unit=?, barcode=?, shelf_life_days=?, abc_class=?,
           safety_stock=?, max_stock=?, remark=?, updated_at=datetime('now','localtime') WHERE id=?""",
        (name, category, spec, unit, barcode, shelf_life, abc_class, safety_stock, max_stock, remark, id)
    )
    db.commit()
    return RedirectResponse("/sku", 303)


@router.post("/{id}/delete")
def delete(id: int, db=Depends(get_db)):
    db.execute("DELETE FROM sku_packages WHERE sku_id=?", (id,))
    db.execute("DELETE FROM skus WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/sku", 303)


# 包装规格
@router.get("/{id}/packages")
def list_packages(id: int, request: Request, db=Depends(get_db)):
    sku = db.execute("SELECT * FROM skus WHERE id=?", (id,)).fetchone()
    if not sku:
        return RedirectResponse("/sku", 303)
    pkgs = db.execute("SELECT * FROM sku_packages WHERE sku_id=? ORDER BY id", (id,)).fetchall()
    return templates.TemplateResponse("sku/packages.html", {
        "request": request, "active_page": "sku", "sku": sku, "packages": pkgs,
    })


@router.post("/{id}/packages/new")
def add_package(id: int, request: Request, package_type: str = Form(""), conversion_qty: float = Form(1),
                barcode: str = Form(""), length: float = Form(None), width: float = Form(None),
                height: float = Form(None), weight: float = Form(None), db=Depends(get_db)):
    sku = db.execute("SELECT * FROM skus WHERE id=?", (id,)).fetchone()
    if not sku:
        return RedirectResponse("/sku", 303)
    if not package_type:
        return templates.TemplateResponse("sku/packages.html", {
            "request": request, "active_page": "sku", "sku": sku,
            "packages": db.execute("SELECT * FROM sku_packages WHERE sku_id=? ORDER BY id", (id,)).fetchall(),
            "error": "请填写必填字段：包装类型",
        })
    db.execute(
        """INSERT INTO sku_packages (sku_id, package_type, conversion_qty, barcode, length, width, height, weight)
           VALUES (?,?,?,?,?,?,?,?)""",
        (id, package_type, conversion_qty, barcode, length, width, height, weight)
    )
    db.commit()
    return RedirectResponse(f"/sku/{id}/packages", 303)


@router.post("/packages/{id}/delete")
def delete_package(id: int, db=Depends(get_db)):
    pkg = db.execute("SELECT * FROM sku_packages WHERE id=?", (id,)).fetchone()
    if pkg:
        sku_id = pkg["sku_id"]
        db.execute("DELETE FROM sku_packages WHERE id=?", (id,))
        db.commit()
        return RedirectResponse(f"/sku/{sku_id}/packages", 303)
    return RedirectResponse("/sku", 303)
