from fastapi import Request, HTTPException
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_passphrase(passphrase: str) -> str:
    return pwd_context.hash(passphrase)


def verify_passphrase(passphrase: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(passphrase, hashed)
    except Exception:
        return False


def get_current_user(request: Request) -> str:
    user = request.cookies.get("feedpipe_user")
    if not user:
        if request.headers.get("HX-Request") == "true":
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"HX-Redirect": "/login"},
            )
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user
