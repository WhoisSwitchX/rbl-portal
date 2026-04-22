from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
# from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
# from main import templates
from app.templates import templates
from markupsafe import Markup
import re

from app.database import get_db
from app import models

router = APIRouter()


# ✅ Highlight filter (FIX)
def highlight(text, query):
    if not text or not query:
        return text

    # support multi-word search
    pattern = "|".join(re.escape(word) for word in query.split())

    highlighted = re.sub(
        f"({pattern})",
        r"<mark>\1</mark>",
        text,
        flags=re.IGNORECASE
    )
    return Markup(highlighted)


# ✅ Register filter with Jinja
# templates.env.filters["highlight"] = highlight


async def get_user(request: Request, db: Session):
    from app.auth import decode_token
    from jose import JWTError

    token = request.cookies.get("access_token")
    if not token:
        return None

    try:
        payload = decode_token(token)
        email = payload.get("sub")
        if not email:
            return None

        return db.query(models.User).filter(models.User.email == email).first()

    except JWTError:
        return None


@router.get("/", response_class=HTMLResponse)
async def search(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    q = q.strip()
    results = []
    total = 0

    if q and len(q) >= 2:
        base = db.query(models.BudgetLine)

        # Role-based filtering
        if user.role == models.UserRole.IT_HEAD:
            base = base.filter(models.BudgetLine.submitted_by == user.id)

        results = base.filter(
            or_(
                models.BudgetLine.budget_key_current.ilike(f"%{q}%"),
                models.BudgetLine.description.ilike(f"%{q}%"),
                models.BudgetLine.expense_description.ilike(f"%{q}%"),
                models.BudgetLine.vendor_name.ilike(f"%{q}%"),
                models.BudgetLine.application_platform.ilike(f"%{q}%"),
                models.BudgetLine.business_name.ilike(f"%{q}%"),
                models.BudgetLine.it_head_name.ilike(f"%{q}%"),
                models.BudgetLine.detailed_reasoning.ilike(f"%{q}%"),
            )
        ).order_by(models.BudgetLine.created_at.desc()).limit(50).all()

        total = len(results)

    return templates.TemplateResponse(
        "search/results.html",
        {
            "request": request,
            "user": user,
            "active_page": "search",
            "q": q,
            "results": results,
            "total": total,
        }
    )