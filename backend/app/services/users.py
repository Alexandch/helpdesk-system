from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_password
from app.models.enums import UserRole
from app.models.user import User


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def create_user(db: Session, email: str, full_name: str, password: str, role: UserRole = UserRole.USER) -> User:
    user = User(
        email=email.lower(),
        full_name=full_name,
        hashed_password=get_password_hash(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email.lower())
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user

