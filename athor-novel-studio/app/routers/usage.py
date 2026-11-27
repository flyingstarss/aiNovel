from fastapi import APIRouter

from app import monitor

router = APIRouter()


@router.get("/api/usage")
def usage(limit: int = 50):
    return monitor.summary(limit)
