from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app import models

router = APIRouter()


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


@router.get("/dummy1")
async def dummy1_list(request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    items = db.query(models.Dummy1).filter(models.Dummy1.is_active == True).all()
    return JSONResponse([{"id": i.id, "title": i.title, "description": i.description} for i in items])


@router.get("/dummy2")
async def dummy2_list(request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    items = db.query(models.Dummy2).order_by(models.Dummy2.created_at.desc()).limit(50).all()
    return JSONResponse([{"id": i.id, "event_type": i.event_type, "event_data": i.event_data} for i in items])
