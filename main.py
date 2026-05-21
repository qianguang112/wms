from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from core.config import APP_TITLE
from core.database import init_db
from routers import dashboard, fixed_asset, office_supply
from routers import warehouse, sku, partner, inbound, outbound, internal, inventory


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=APP_TITLE, lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    messages = []
    for e in errors:
        field = ".".join(str(loc) for loc in e["loc"] if loc != "body")
        msg = e.get("msg", "")
        if msg == "field required":
            messages.append(f"请填写：{field}")
        elif "valid integer" in msg:
            messages.append(f"请填写有效数字：{field}")
        elif "valid list" in msg:
            messages.append(f"请选择：{field}")
        else:
            messages.append(f"{field} 格式不正确")
    error_str = "；".join(messages)
    referer = request.headers.get("referer", "/")
    # Avoid redirect loop — if referer already has error param, strip it first
    from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
    parsed = urlparse(referer)
    query = {k: v[0] for k, v in parse_qs(parsed.query).items() if k != "error"}
    query["error"] = error_str
    new_query = urlencode(query)
    new_url = parsed._replace(query=new_query).geturl()
    return RedirectResponse(new_url, 303)


app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(dashboard.router)
app.include_router(fixed_asset.router)
app.include_router(office_supply.router)
app.include_router(warehouse.router)
app.include_router(sku.router)
app.include_router(partner.router)
app.include_router(inbound.router)
app.include_router(outbound.router)
app.include_router(internal.router)
app.include_router(inventory.router)

if __name__ == "__main__":
    import uvicorn
    import socket
    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    print(f"\n  系统启动成功！")
    print(f"  本机访问: http://localhost:8000")
    print(f"  局域网访问: http://{ip}:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
