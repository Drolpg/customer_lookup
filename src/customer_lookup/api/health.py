from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: o processo está de pé")
def health() -> dict[str, str]:
    return {"status": "ok"}
