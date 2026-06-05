from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_passphrase(passphrase: str) -> str:
    return pwd_context.hash(passphrase)


def verify_passphrase(passphrase: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(passphrase, hashed)
    except Exception:
        return False
