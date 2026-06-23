from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_super_admin
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserRead, UserUpdate


router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(_: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())))


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: str, payload: UserUpdate, current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    values = payload.model_dump(exclude_unset=True)
    removes_super_admin = user.role == UserRole.SUPER_ADMIN and (
        values.get("role", UserRole.SUPER_ADMIN) != UserRole.SUPER_ADMIN
        or values.get("is_active") is False
    )
    if removes_super_admin:
        active_super_admins = db.scalar(
            select(func.count(User.id)).where(
                User.role == UserRole.SUPER_ADMIN,
                User.is_active.is_(True),
            )
        )
        if active_super_admins <= 1:
            raise HTTPException(status_code=422, detail="At least one active super admin is required")
    if user.id == current_user.id and values.get("is_active") is False:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account")
    for key, value in values.items():
        setattr(user, key, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
