from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates, CONTAINER_TYPES, CONTAINER_TYPE_LABELS
from utils.helpers import generate_container_code, safe_create

router = APIRouter(prefix="/container")


@router.get("")
def list_containers(request: Request, container_type: str = "", status: str = "", db=Depends(get_db)):
    sql = """SELECT c.*, l.code as location_code FROM containers c
             LEFT JOIN locations l ON c.location_id = l.id WHERE 1=1"""
    params = []
    if container_type:
        sql += " AND c.container_type=?"
        params.append(container_type)
    if status:
        sql += " AND c.status=?"
        params.append(status)
    sql += " ORDER BY c.id DESC"
    rows = db.execute(sql, params).fetchall()
    return templates.TemplateResponse("container/list.html", {
        "request": request, "active_page": "containers",
        "rows": rows, "container_type": container_type, "status": status,
        "container_types": CONTAINER_TYPES, "container_type_labels": CONTAINER_TYPE_LABELS,
    })


@router.get("/new")
def new_form(request: Request, db=Depends(get_db)):
    locations = db.execute("SELECT l.*, a.name as area_name FROM locations l JOIN warehouse_areas a ON l.area_id=a.id ORDER BY a.name, l.code").fetchall()
    return templates.TemplateResponse("container/form.html", {
        "request": request, "active_page": "containers", "container": None,
        "container_types": CONTAINER_TYPES, "container_type_labels": CONTAINER_TYPE_LABELS,
        "locations": locations,
    })


@router.post("/new")
def create(container_type: str = Form("pallet"), capacity: float = Form(0),
           location_id: int = Form(None), db=Depends(get_db)):

    def do_insert():
        code = generate_container_code(db)
        db.execute(
            "INSERT INTO containers (code, container_type, capacity, location_id) VALUES (?,?,?,?)",
            (code, container_type, capacity, location_id if location_id else None)
        )
        db.commit()

    safe_create(db, do_insert)
    return RedirectResponse("/container", 303)


@router.get("/{id}/edit")
def edit_form(id: int, request: Request, db=Depends(get_db)):
    c = db.execute("SELECT * FROM containers WHERE id=?", (id,)).fetchone()
    if not c:
        return RedirectResponse("/container", 303)
    locations = db.execute("SELECT l.*, a.name as area_name FROM locations l JOIN warehouse_areas a ON l.area_id=a.id ORDER BY a.name, l.code").fetchall()
    return templates.TemplateResponse("container/form.html", {
        "request": request, "active_page": "containers", "container": c,
        "container_types": CONTAINER_TYPES, "container_type_labels": CONTAINER_TYPE_LABELS,
        "locations": locations,
    })


@router.post("/{id}/edit")
def update(id: int, container_type: str = Form("pallet"), capacity: float = Form(0),
           location_id: int = Form(None), status: str = Form("idle"), db=Depends(get_db)):
    db.execute(
        """UPDATE containers SET container_type=?, capacity=?, location_id=?, status=?,
           updated_at=datetime('now','localtime') WHERE id=?""",
        (container_type, capacity, location_id if location_id else None, status, id)
    )
    db.commit()
    return RedirectResponse("/container", 303)


@router.post("/{id}/delete")
def delete(id: int, db=Depends(get_db)):
    db.execute("DELETE FROM containers WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/container", 303)
