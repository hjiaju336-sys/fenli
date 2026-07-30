"""简易 JWT — Python 内置库，零依赖"""
import json, hmac, hashlib, base64, time, os

SECRET = os.environ.get("JWT_SECRET", os.urandom(32).hex())

def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def b64d(s: str) -> bytes:
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)

def create_token(player_id: str, username: str) -> str:
    header = b64e(json.dumps({"alg":"HS256","typ":"JWT"}).encode())
    payload = b64e(json.dumps({"pid":player_id,"name":username,"exp":int(time.time())+86400*30}).encode())
    sig = b64e(hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"

def verify_token(token: str) -> dict|None:
    try:
        parts = token.split(".")
        if len(parts) != 3: return None
        header, payload, sig = parts
        expected = b64e(hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if sig != expected: return None
        data = json.loads(b64d(payload))
        if data.get("exp", 0) < time.time(): return None
        return data
    except Exception:
        return None
