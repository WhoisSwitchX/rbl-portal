from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app import models
from app.auth import generate_budget_key

router    = APIRouter()
templates = Jinja2Templates(directory="app/templates")

BUSINESS_COST_MAP = {
    "Operation Technology" : 3709,
    "RISK Technology"      : 3708,
    "Technology infra"     : 3701,
    "Technology operations": 3717,
    "Technology others"    : 3722,
    "Technology shared DWH": 3716,
    "Treasury"             : 3714,
}

BUSINESS_NAMES   = list(BUSINESS_COST_MAP.keys())
EXPENSE_TYPES    = [e.value for e in models.ExpenseSubType]
OLD_NEW_OPTIONS  = [o.value for o in models.OldNew]


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
async def budget_list(request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    q = db.query(models.BudgetLine)
    if user.role == models.UserRole.IT_HEAD:
        q = q.filter(models.BudgetLine.submitted_by == user.id)
    lines = q.order_by(models.BudgetLine.created_at.desc()).all()

    counts = {
        "draft"    : sum(1 for l in lines if l.status == models.BudgetStatus.DRAFT),
        "submitted": sum(1 for l in lines if l.status == models.BudgetStatus.SUBMITTED),
        "approved" : sum(1 for l in lines if l.status == models.BudgetStatus.FINAL_APPROVED),
    }

    imported = request.query_params.get("imported")
    skipped  = request.query_params.get("skipped")

    return templates.TemplateResponse("budget/list.html", {
        "request"    :request,
        "user"    : user,
        "lines"   : lines,
        "counts"  : counts,
        "imported": imported,
        "skipped" : skipped,
        "active_page": "budget",
    })


@router.get("/new", response_class=HTMLResponse)
async def new_form(request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    if user.role != models.UserRole.IT_HEAD:
        return RedirectResponse(url="/dashboard/", status_code=302)

    return templates.TemplateResponse("budget/form.html", {
        "request"    :request,
        "user"           : user,
        "next_key"       : generate_budget_key(db),
        "entry"          : None,
        "error"          : None,
        "active_page"    : "new_entry",
        "BUSINESS_NAMES" : BUSINESS_NAMES,
        "BUSINESS_COST_MAP": BUSINESS_COST_MAP,
        "EXPENSE_TYPES"  : EXPENSE_TYPES,
        "OLD_NEW_OPTIONS": OLD_NEW_OPTIONS,
    })


@router.post("/new")
async def create_entry(
    request              : Request,
    db                   : Session = Depends(get_db),
    old_new              : str     = Form(...),
    budget_key_previous  : Optional[str]   = Form(None),
    business_name        : str     = Form(...),
    expense_sub_type     : str     = Form(...),
    description          : str     = Form(...),
    expense_description  : Optional[str]   = Form(None),
    application_platform : Optional[str]   = Form(None),
    vendor_name          : Optional[str]   = Form(None),
    resource_count       : Optional[int]   = Form(None),
    budget_amt_current_fy: float   = Form(...),
    projected_consumption: Optional[float] = Form(None),
    budget_amt_next_fy   : float   = Form(...),
    detailed_reasoning   : Optional[str]   = Form(None),
    action               : str     = Form("draft"),
):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    a = budget_amt_current_fy
    b = projected_consumption
    c = budget_amt_next_fy

    entry = models.BudgetLine(
        budget_key_current   = generate_budget_key(db),
        budget_key_previous  = budget_key_previous if old_new == "Old" or old_new == "Old But Incremental" else None,
        old_new              = models.OldNew(old_new),
        business_name        = business_name,
        cost_code            = BUSINESS_COST_MAP.get(business_name, 0),
        submitted_by         = user.id,
        it_head_name         = user.full_name,
        spoc_name            = user.spoc_name,
        expense_sub_type     = models.ExpenseSubType(expense_sub_type),
        description          = description,
        expense_description  = expense_description,
        application_platform = application_platform,
        vendor_name          = vendor_name,
        resource_count       = resource_count,
        budget_amt_current_fy= a,
        projected_consumption= b,
        budget_amt_next_fy   = c,
        diff_a_minus_b       = (a - b) if b is not None else None,
        diff_c_minus_b       = (c - b) if b is not None else None,
        diff_c_minus_a       = c - a,
        detailed_reasoning   = detailed_reasoning,
        status               = models.BudgetStatus.SUBMITTED if action == "submit" else models.BudgetStatus.DRAFT,
    )
    db.add(entry)
    db.commit()
    return RedirectResponse(url="/budget/", status_code=302)


@router.post("/{entry_id}/submit")
async def submit_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    entry = db.query(models.BudgetLine).filter(
        models.BudgetLine.id == entry_id,
        models.BudgetLine.submitted_by == user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")
    if entry.status != models.BudgetStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only DRAFT can be submitted")
    entry.status = models.BudgetStatus.SUBMITTED
    db.commit()
    return RedirectResponse(url="/budget/", status_code=302)


@router.post("/{entry_id}/delete")
async def delete_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)
    entry = db.query(models.BudgetLine).filter(
        models.BudgetLine.id == entry_id,
        models.BudgetLine.submitted_by == user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Not found")
    if entry.status != models.BudgetStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only DRAFT can be deleted")
    db.delete(entry)
    db.commit()
    return RedirectResponse(url="/budget/", status_code=302)
