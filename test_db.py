from app.database import SessionLocal
from app.models import User

db = SessionLocal()

users = db.query(User).all()

for user in users:
    print(user.id, user.full_name, user.email)

db.close()