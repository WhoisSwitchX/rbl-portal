from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app import models

router    = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def get_user(request: Request, db: Session):
    from app.auth import decode_token
    from jose import JWTError
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = decode_token(token)
        email   = payload.get("sub")
        if not email:
            return None
        return db.query(models.User).filter(models.User.email == email).first()
    except JWTError:
        return None


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    q = db.query(models.BudgetLine)
    if user.role == models.UserRole.IT_HEAD:
        q = q.filter(models.BudgetLine.submitted_by == user.id)
    lines = q.all()

    total_budget = sum(l.budget_amt_current_fy for l in lines)
    it_head_data = {}
    for line in lines:
        u    = db.query(models.User).filter(models.User.id == line.submitted_by).first()
        name = u.full_name if u else "Unknown"
        if name not in it_head_data:
            it_head_data[name] = {"budget": 0, "projected": 0}
        it_head_data[name]["budget"]    += line.budget_amt_current_fy
        it_head_data[name]["projected"] += (line.projected_consumption or 0)

    # Group by expense sub type
    by_type = {}
    for line in lines:
        t = line.expense_sub_type.value
        by_type[t] = by_type.get(t, 0) + line.budget_amt_current_fy

    kpi = {
        "total_budget": total_budget,
        "budget_keys" : len(set(l.budget_key_current for l in lines)),
        "it_heads"    : len(set(l.submitted_by for l in lines)),
        "by_type"     : by_type,
    }

    return templates.TemplateResponse("dashboard/index.html", {
        "request"    :request,
        "user"        : user,
        "kpi"         : kpi,
        "it_head_data": it_head_data,
        "recent_lines": lines[:5],
        "active_page" : "dashboard",
    })


@router.get("/kpi")
async def kpi_json(request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    lines = db.query(models.BudgetLine).all()
    it_head_data = {}
    for line in lines:
        u    = db.query(models.User).filter(models.User.id == line.submitted_by).first()
        name = u.full_name if u else "Unknown"
        if name not in it_head_data:
            it_head_data[name] = {"budget": 0, "projected": 0}
        it_head_data[name]["budget"]    += line.budget_amt_current_fy
        it_head_data[name]["projected"] += (line.projected_consumption or 0)
    by_type = {}
    for line in lines:
        t = line.expense_sub_type.value
        by_type[t] = by_type.get(t, 0) + line.budget_amt_current_fy
    return JSONResponse({
        "labels"   : list(it_head_data.keys()),
        "budget"   : [v["budget"]    for v in it_head_data.values()],
        "projected": [v["projected"] for v in it_head_data.values()],
        "by_type"  : by_type,
    })
