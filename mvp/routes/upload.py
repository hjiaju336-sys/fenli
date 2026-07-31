"""图片上传 — 从 server.py 提取"""
import pathlib
import uuid

from fastapi import APIRouter, Request, HTTPException, UploadFile, File

from middleware import _pid

router = APIRouter()

_UPLOAD_DIR = pathlib.Path(__file__).parent.parent / "static" / "uploads"
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGES_PER_USER = 50

# Magic bytes for format validation
_MAGIC_BYTES = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG\r\n\x1a\n": ".png",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"RIFF": ".webp",  # RIFF....WEBP
}


def _validate_image_magic(content: bytes) -> str:
    """通过magic bytes验证图片格式，返回扩展名（含点）"""
    for magic, ext in _MAGIC_BYTES.items():
        if content[:len(magic)] == magic:
            if ext == ".webp":
                # WebP需要额外检查: RIFFxxxxWEBP
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    return ext
                continue
            return ext
    return ""


def _count_user_images(pid: str) -> int:
    """统计某用户的图片数量"""
    user_dir = _UPLOAD_DIR / pid
    if not user_dir.exists():
        return 0
    return len([f for f in user_dir.iterdir()
                if f.is_file() and f.suffix.lower() in _ALLOWED_EXTENSIONS])


@router.post("/api/upload/image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    pid = _pid(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # 检查扩展名
    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext}. Allowed: jpg, png, gif, webp",
        )

    # 读取文件内容
    content = await file.read()

    # 大小检查
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 2MB)")

    # Magic bytes验证
    detected_ext = _validate_image_magic(content)
    if not detected_ext:
        raise HTTPException(
            status_code=400, detail="Invalid image file (magic bytes mismatch)"
        )

    # 使用检测到的扩展名（更可靠）
    if detected_ext != ext:
        ext = detected_ext

    # 配额检查
    user_dir = _UPLOAD_DIR / pid
    user_dir.mkdir(parents=True, exist_ok=True)
    current_count = _count_user_images(pid)
    if current_count >= _MAX_IMAGES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Image quota exceeded ({_MAX_IMAGES_PER_USER} max). "
                   f"Please delete some images first.",
        )

    # 保存文件
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = user_dir / filename
    with open(filepath, "wb") as f:
        f.write(content)

    url = f"/static/uploads/{pid}/{filename}"
    return {"url": url, "filename": filename, "size": len(content)}


@router.get("/api/upload/images")
def list_images(request: Request):
    pid = _pid(request)
    user_dir = _UPLOAD_DIR / pid
    if not user_dir.exists():
        return {"images": [], "count": 0, "quota": _MAX_IMAGES_PER_USER}
    images = []
    for f in sorted(user_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in _ALLOWED_EXTENSIONS:
            images.append({
                "filename": f.name,
                "url": f"/static/uploads/{pid}/{f.name}",
                "size": f.stat().st_size,
            })
    return {"images": images, "count": len(images), "quota": _MAX_IMAGES_PER_USER}


@router.delete("/api/upload/image/{filename}")
def delete_image(filename: str, request: Request):
    pid = _pid(request)
    # 安全检查：防止路径遍历
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = _UPLOAD_DIR / pid / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        filepath.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")
    return {"ok": True}
