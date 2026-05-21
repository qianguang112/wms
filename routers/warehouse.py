from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from core.database import get_db
from core.config import templates, AREA_TYPES, AREA_TYPE_LABELS, LOCATION_STATUS_LABELS, LOCATION_STATUS_COLORS
from utils.helpers import generate_warehouse_code, generate_area_code

router = APIRouter(prefix="/warehouse")


# ======================== 仓库 ========================
@router.get("")
def list_warehouses(request: Request, db=Depends(get_db)):
    rows = db.execute("SELECT * FROM warehouses ORDER BY id DESC").fetchall()
    return templates.TemplateResponse("warehouse/list.html", {
        "request": request, "active_page": "warehouse", "rows": rows,
    })


@router.get("/new")
def new_warehouse_form(request: Request):
    return templates.TemplateResponse("warehouse/form.html", {
        "request": request, "active_page": "warehouse", "warehouse": None,
    })


@router.post("/new")
def create_warehouse(request: Request, name: str = Form(""), address: str = Form(""),
                     manager: str = Form(""), db=Depends(get_db)):
    if not name:
        return templates.TemplateResponse("warehouse/form.html", {
            "request": request, "active_page": "warehouse", "warehouse": None,
            "error": "请填写必填字段：仓库名称",
        })
    code = generate_warehouse_code(db)
    db.execute("INSERT INTO warehouses (code, name, address, manager) VALUES (?,?,?,?)",
               (code, name, address, manager))
    db.commit()
    return RedirectResponse("/warehouse", 303)


@router.get("/{id}/edit")
def edit_warehouse_form(id: int, request: Request, db=Depends(get_db)):
    wh = db.execute("SELECT * FROM warehouses WHERE id=?", (id,)).fetchone()
    if not wh:
        return RedirectResponse("/warehouse", 303)
    return templates.TemplateResponse("warehouse/form.html", {
        "request": request, "active_page": "warehouse", "warehouse": wh,
    })


@router.post("/{id}/edit")
def update_warehouse(id: int, request: Request, name: str = Form(""), address: str = Form(""),
                     manager: str = Form(""), db=Depends(get_db)):
    wh = db.execute("SELECT * FROM warehouses WHERE id=?", (id,)).fetchone()
    if not wh:
        return RedirectResponse("/warehouse", 303)
    if not name:
        return templates.TemplateResponse("warehouse/form.html", {
            "request": request, "active_page": "warehouse",
            "warehouse": {"id": id, "name": name, "address": address, "manager": manager},
            "error": "请填写必填字段：仓库名称",
        })
    db.execute("UPDATE warehouses SET name=?, address=?, manager=?, updated_at=datetime('now','localtime') WHERE id=?",
               (name, address, manager, id))
    db.commit()
    return RedirectResponse("/warehouse", 303)


@router.post("/{id}/delete")
def delete_warehouse(id: int, db=Depends(get_db)):
    db.execute("DELETE FROM locations WHERE area_id IN (SELECT id FROM warehouse_areas WHERE warehouse_id=?)", (id,))
    db.execute("DELETE FROM warehouse_areas WHERE warehouse_id=?", (id,))
    db.execute("DELETE FROM warehouses WHERE id=?", (id,))
    db.commit()
    return RedirectResponse("/warehouse", 303)


# ======================== 库区 ========================
@router.get("/{id}/areas")
def list_areas(id: int, request: Request, db=Depends(get_db)):
    wh = db.execute("SELECT * FROM warehouses WHERE id=?", (id,)).fetchone()
    if not wh:
        return RedirectResponse("/warehouse", 303)
    areas = db.execute("SELECT * FROM warehouse_areas WHERE warehouse_id=? ORDER BY code", (id,)).fetchall()
    return templates.TemplateResponse("warehouse/areas.html", {
        "request": request, "active_page": "warehouse", "warehouse": wh, "areas": areas,
        "area_type_labels": AREA_TYPE_LABELS,
    })


@router.get("/{id}/areas/new")
def new_area_form(id: int, request: Request, db=Depends(get_db)):
    wh = db.execute("SELECT * FROM warehouses WHERE id=?", (id,)).fetchone()
    if not wh:
        return RedirectResponse("/warehouse", 303)
    return templates.TemplateResponse("warehouse/area_form.html", {
        "request": request, "active_page": "warehouse", "warehouse": wh, "area": None,
        "area_types": AREA_TYPES, "area_type_labels": AREA_TYPE_LABELS,
    })


@router.post("/{id}/areas/new")
def create_area(id: int, request: Request, name: str = Form(""), area_type: str = Form("ambient"),
                temp_min: str = Form(""), temp_max: str = Form(""), db=Depends(get_db)):
    wh = db.execute("SELECT * FROM warehouses WHERE id=?", (id,)).fetchone()
    if not wh:
        return RedirectResponse("/warehouse", 303)
    if not name:
        return templates.TemplateResponse("warehouse/area_form.html", {
            "request": request, "active_page": "warehouse", "warehouse": wh, "area": None,
            "area_types": AREA_TYPES, "area_type_labels": AREA_TYPE_LABELS,
            "error": "请填写必填字段：库区名称",
        })
    _tmin = float(temp_min) if temp_min.strip() else None
    _tmax = float(temp_max) if temp_max.strip() else None
    code = generate_area_code(db)
    db.execute(
        "INSERT INTO warehouse_areas (warehouse_id, code, name, area_type, temp_min, temp_max) VALUES (?,?,?,?,?,?)",
        (id, code, name, area_type, _tmin, _tmax)
    )
    db.commit()
    return RedirectResponse(f"/warehouse/{id}/areas", 303)


@router.post("/areas/{id}/delete")
def delete_area(id: int, db=Depends(get_db)):
    area = db.execute("SELECT * FROM warehouse_areas WHERE id=?", (id,)).fetchone()
    if not area:
        return RedirectResponse("/warehouse", 303)
    loc_ids = [r["id"] for r in db.execute("SELECT id FROM locations WHERE area_id=?", (id,)).fetchall()]
    if loc_ids:
        placeholders = ",".join("?" * len(loc_ids))
        db.execute(f"DELETE FROM inventory_transactions WHERE location_id IN ({placeholders})", loc_ids)
        db.execute(f"DELETE FROM inventory_blocks WHERE inventory_id IN (SELECT id FROM inventory WHERE location_id IN ({placeholders}))", loc_ids)
        db.execute(f"DELETE FROM pick_tasks WHERE location_id IN ({placeholders})", loc_ids)
        db.execute(f"DELETE FROM wave_lines WHERE location_id IN ({placeholders})", loc_ids)
        db.execute(f"DELETE FROM putaway_tasks WHERE to_location_id IN ({placeholders})", loc_ids)
        db.execute(f"DELETE FROM stock_moves WHERE from_location_id IN ({placeholders}) OR to_location_id IN ({placeholders})", loc_ids)
        db.execute(f"DELETE FROM count_tasks WHERE location_id IN ({placeholders})", loc_ids)
        db.execute(f"DELETE FROM containers WHERE location_id IN ({placeholders})", loc_ids)
        db.execute(f"DELETE FROM inventory WHERE location_id IN ({placeholders})", loc_ids)
        db.execute(f"DELETE FROM locations WHERE area_id=?", (id,))
    db.execute("DELETE FROM warehouse_areas WHERE id=?", (id,))
    db.commit()
    return RedirectResponse(f"/warehouse/{area['warehouse_id']}/areas", 303)


# ======================== 库位 ========================
@router.get("/areas/{id}/locations")
def list_locations(id: int, request: Request, db=Depends(get_db)):
    area = db.execute(
        "SELECT a.*, w.name as warehouse_name, w.id as warehouse_id FROM warehouse_areas a JOIN warehouses w ON a.warehouse_id=w.id WHERE a.id=?",
        (id,)
    ).fetchone()
    if not area:
        return RedirectResponse("/warehouse", 303)
    locs = db.execute("SELECT * FROM locations WHERE area_id=? ORDER BY code", (id,)).fetchall()
    return templates.TemplateResponse("warehouse/locations.html", {
        "request": request, "active_page": "warehouse", "area": area, "locs": locs,
        "status_labels": LOCATION_STATUS_LABELS,
    })


@router.get("/areas/{id}/locations/new")
def new_location_form(id: int, request: Request, db=Depends(get_db)):
    area = db.execute("SELECT * FROM warehouse_areas WHERE id=?", (id,)).fetchone()
    if not area:
        return RedirectResponse("/warehouse", 303)
    return templates.TemplateResponse("warehouse/location_form.html", {
        "request": request, "active_page": "warehouse", "area": area, "location": None,
    })


@router.post("/areas/{id}/locations/new")
def create_location(id: int, request: Request, code: str = Form(""), capacity: float = Form(1),
                    db=Depends(get_db)):
    area = db.execute("SELECT * FROM warehouse_areas WHERE id=?", (id,)).fetchone()
    if not area:
        return RedirectResponse("/warehouse", 303)
    if not code:
        return templates.TemplateResponse("warehouse/location_form.html", {
            "request": request, "active_page": "warehouse", "area": area, "location": None,
            "error": "请填写必填字段：库位编码",
        })
    parts = code.strip().split("-")
    zone_code = parts[0] if len(parts) > 0 else ""
    row_no = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    col_no = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    level_no = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    db.execute(
        """INSERT INTO locations (area_id, code, zone_code, row_no, col_no, level_no, capacity)
           VALUES (?,?,?,?,?,?,?)""",
        (id, code.strip(), zone_code, row_no, col_no, level_no, capacity)
    )
    db.commit()
    return RedirectResponse(f"/warehouse/areas/{id}/locations", 303)


@router.post("/areas/{id}/locations/batch")
def batch_create_locations(id: int, request: Request, zone: str = Form(""),
                           rows_from: int = Form(1), rows_to: int = Form(5),
                           cols_from: int = Form(1), cols_to: int = Form(10),
                           levels_from: int = Form(1), levels_to: int = Form(3),
                           capacity: float = Form(1), db=Depends(get_db)):
    area = db.execute("SELECT * FROM warehouse_areas WHERE id=?", (id,)).fetchone()
    if not area:
        return RedirectResponse("/warehouse", 303)
    if not zone:
        return templates.TemplateResponse("warehouse/locations.html", {
            "request": request, "active_page": "warehouse", "area": area,
            "locs": db.execute("SELECT * FROM locations WHERE area_id=? ORDER BY code", (id,)).fetchall(),
            "status_labels": LOCATION_STATUS_LABELS,
            "error": "请填写必填字段：分区编码（如 A）",
        })
    for r in range(rows_from, rows_to + 1):
        for c in range(cols_from, cols_to + 1):
            for l in range(levels_from, levels_to + 1):
                code = f"{zone}-{r:02d}-{c:02d}-{l:02d}"
                try:
                    db.execute(
                        """INSERT INTO locations (area_id, code, zone_code, row_no, col_no, level_no, capacity)
                           VALUES (?,?,?,?,?,?,?)""",
                        (id, code, zone, r, c, l, capacity)
                    )
                except:
                    pass  # 跳过重复编码
    db.commit()
    return RedirectResponse(f"/warehouse/areas/{id}/locations", 303)


@router.post("/locations/{id}/delete")
def delete_location(id: int, db=Depends(get_db)):
    loc = db.execute("SELECT * FROM locations WHERE id=?", (id,)).fetchone()
    if not loc:
        return RedirectResponse("/warehouse", 303)
    area_id = loc["area_id"]
    db.execute("DELETE FROM inventory_transactions WHERE location_id=?", (id,))
    db.execute("DELETE FROM inventory_blocks WHERE inventory_id IN (SELECT id FROM inventory WHERE location_id=?)", (id,))
    db.execute("DELETE FROM pick_tasks WHERE location_id=?", (id,))
    db.execute("DELETE FROM wave_lines WHERE location_id=?", (id,))
    db.execute("DELETE FROM putaway_tasks WHERE to_location_id=?", (id,))
    db.execute("DELETE FROM stock_moves WHERE from_location_id=? OR to_location_id=?", (id, id))
    db.execute("DELETE FROM count_tasks WHERE location_id=?", (id,))
    db.execute("DELETE FROM containers WHERE location_id=?", (id,))
    db.execute("DELETE FROM inventory WHERE location_id=?", (id,))
    db.execute("DELETE FROM locations WHERE id=?", (id,))
    db.commit()
    return RedirectResponse(f"/warehouse/areas/{area_id}/locations", 303)


# ======================== 库位可视化 ========================
@router.get("/areas/{id}/map")
def location_map(id: int, request: Request, db=Depends(get_db)):
    area = db.execute(
        "SELECT a.*, w.name as warehouse_name FROM warehouse_areas a JOIN warehouses w ON a.warehouse_id=w.id WHERE a.id=?",
        (id,)
    ).fetchone()
    if not area:
        return RedirectResponse("/warehouse", 303)
    locs = db.execute("SELECT * FROM locations WHERE area_id=? ORDER BY row_no, col_no, level_no", (id,)).fetchall()

    # 构建2D网格数据
    max_row = max((l["row_no"] for l in locs), default=0)
    max_col = max((l["col_no"] for l in locs), default=0)
    grid = {}
    for loc in locs:
        grid[(loc["row_no"], loc["col_no"], loc["level_no"])] = loc

    return templates.TemplateResponse("warehouse/location_map.html", {
        "request": request, "active_page": "warehouse", "area": area, "locs": locs,
        "max_row": max_row, "max_col": max_col, "grid": grid,
        "status_colors": LOCATION_STATUS_COLORS, "status_labels": LOCATION_STATUS_LABELS,
    })
