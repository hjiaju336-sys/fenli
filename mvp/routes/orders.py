"""订单系统 — 积分购买、订单管理"""
import time
import hashlib as _hl
import hmac
import base64

from fastapi import APIRouter, Request
from sqlalchemy import text

from db import get_session
from middleware import _pid, _admin_pid, XCHG_SECRET

router = APIRouter()


def _gen_exchange_code(points: int, batch: str = "SHOP") -> str:
    """生成 HMAC 签名兑换码"""
    raw = f"{batch}-{points}-{time.time()}"
    sig = hmac.new(
        XCHG_SECRET.encode(),
        raw.encode(),
        "sha256"
    ).digest()
    encoded = base64.b32encode(sig).decode().rstrip("=")[:12]
    chunks = [encoded[i:i+4] for i in range(0, 12, 4)]
    return f"FL-{'-'.join(chunks)}"


def _create_orders_table(session):
    """创建订单表（如不存在）"""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS point_orders (
            id INT AUTO_INCREMENT PRIMARY KEY,
            player_id VARCHAR(255),
            price INT DEFAULT 0,
            points INT DEFAULT 0,
            package_name VARCHAR(100) DEFAULT '',
            payer_info VARCHAR(255) DEFAULT '',
            payment_ref VARCHAR(255) DEFAULT '',
            status VARCHAR(20) DEFAULT 'pending',
            exchange_code VARCHAR(64) DEFAULT '',
            created_at VARCHAR(50) DEFAULT '',
            updated_at VARCHAR(50) DEFAULT ''
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))
    session.commit()


@router.post("/api/orders")
async def create_order(request: Request):
    """用户提交购买订单"""
    pid = _pid(request)
    body = await request.json()
    price = body.get("price", 0)
    points = body.get("points", 0)
    package = body.get("package", "")
    payer = (body.get("payer", "") or "").strip()
    ref = (body.get("ref", "") or "").strip()

    if not price or not points:
        return {"error": "参数不完整"}
    if not payer or not ref:
        return {"error": "请填写支付账号和转账单号"}

    s = get_session()
    try:
        _create_orders_table(s)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        s.execute(text(
            "INSERT INTO point_orders "
            "(player_id, price, points, package_name, payer_info, payment_ref, "
            "status, created_at, updated_at) "
            "VALUES (:pid, :pr, :pts, :pkg, :payer, :ref, 'pending', :ca, :ca)"
        ), {
            "pid": pid, "pr": price, "pts": points, "pkg": package,
            "payer": payer, "ref": ref, "ca": now
        })
        s.commit()
        return {"ok": True, "message": "订单已提交，管理员核对后将发放兑换码"}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.get("/api/orders/my")
def my_orders(request: Request, page: int = 1, size: int = 20):
    """用户查看自己的订单"""
    pid = _pid(request)
    s = get_session()
    try:
        _create_orders_table(s)
        offset = (page - 1) * size
        total = s.execute(text(
            "SELECT COUNT(*) FROM point_orders WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, price, points, package_name, status, exchange_code, "
            "created_at, updated_at FROM point_orders "
            "WHERE player_id=:pid ORDER BY id DESC LIMIT :lim OFFSET :off"
        ), {"pid": pid, "lim": size, "off": offset}).fetchall()
        orders = [{
            "id": r[0], "price": r[1], "points": r[2],
            "package_name": r[3], "status": r[4],
            "exchange_code": r[5] or "", "created_at": r[6],
            "updated_at": r[7],
        } for r in rows]
        return {"orders": orders, "total": total, "page": page}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 管理端 ──

@router.get("/api/admin/orders")
def admin_orders(request: Request, status: str = "pending", page: int = 1, size: int = 50):
    """管理员查看订单"""
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        _create_orders_table(s)
        offset = (page - 1) * size
        if status == "all":
            total = s.execute(text(
                "SELECT COUNT(*) FROM point_orders"
            )).fetchone()[0]
            rows = s.execute(text(
                "SELECT o.id, o.player_id, u.username, o.price, o.points, "
                "o.package_name, o.payer_info, o.payment_ref, o.status, "
                "o.exchange_code, o.created_at, o.updated_at "
                "FROM point_orders o LEFT JOIN users u ON o.player_id=u.player_id "
                "ORDER BY o.id DESC LIMIT :lim OFFSET :off"
            ), {"lim": size, "off": offset}).fetchall()
        else:
            total = s.execute(text(
                "SELECT COUNT(*) FROM point_orders WHERE status=:st"
            ), {"st": status}).fetchone()[0]
            rows = s.execute(text(
                "SELECT o.id, o.player_id, u.username, o.price, o.points, "
                "o.package_name, o.payer_info, o.payment_ref, o.status, "
                "o.exchange_code, o.created_at, o.updated_at "
                "FROM point_orders o LEFT JOIN users u ON o.player_id=u.player_id "
                "WHERE o.status=:st ORDER BY o.id DESC LIMIT :lim OFFSET :off"
            ), {"st": status, "lim": size, "off": offset}).fetchall()
        orders = [{
            "id": r[0], "player_id": r[1], "username": r[2] or "",
            "price": r[3], "points": r[4], "package_name": r[5],
            "payer_info": r[6], "payment_ref": r[7], "status": r[8],
            "exchange_code": r[9] or "", "created_at": r[10],
            "updated_at": r[11],
        } for r in rows]
        return {"orders": orders, "total": total, "page": page}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/admin/orders/{order_id}/approve")
async def admin_approve_order(order_id: int, request: Request):
    """管理员核发订单 — 生成兑换码"""
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        _create_orders_table(s)
        order = s.execute(text(
            "SELECT id, player_id, points, status FROM point_orders WHERE id=:oid"
        ), {"oid": order_id}).fetchone()
        if not order:
            return {"error": "订单不存在"}
        if order[3] != "pending":
            return {"error": "订单已处理过"}

        code = _gen_exchange_code(order[2], "SHOP")
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        # 更新订单状态
        s.execute(text(
            "UPDATE point_orders SET status='paid', exchange_code=:cd, "
            "updated_at=:ca WHERE id=:oid"
        ), {"cd": code, "ca": now, "oid": order_id})

        # 写入兑换码表
        s.execute(text(
            "INSERT INTO exchange_codes (code, points, batch_id, created_by, "
            "is_used, created_at) VALUES (:cd, :pts, :batch, :pid, 0, :ca)"
        ), {"cd": code, "pts": order[2], "batch": "SHOP",
            "pid": pid, "ca": now})

        # 发送通知（通过系统公告）
        s.execute(text(
            "INSERT INTO system_announcements "
            "(title, content, target_player_id, is_active, created_at) "
            "VALUES ('订单已处理', :msg, :tid, 1, :ca)"
        ), {
            "msg": f"您的{order[2]}积分购买订单已处理！兑换码：{code}，请在个人中心兑换。",
            "tid": order[1], "ca": now
        })

        s.commit()
        return {"ok": True, "exchange_code": code, "message": f"已核发兑换码 {code}"}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/admin/orders/{order_id}/reject")
async def admin_reject_order(order_id: int, request: Request):
    """管理员拒绝订单"""
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        order = s.execute(text(
            "SELECT id, player_id, points, status FROM point_orders WHERE id=:oid"
        ), {"oid": order_id}).fetchone()
        if not order:
            return {"error": "订单不存在"}
        if order[3] != "pending":
            return {"error": "订单已处理过"}
        s.execute(text(
            "UPDATE point_orders SET status='rejected', updated_at=:ca "
            "WHERE id=:oid AND status='pending'"
        ), {"ca": now, "oid": order_id})
        # 发送拒绝通知
        s.execute(text(
            "INSERT INTO system_announcements "
            "(title, content, target_player_id, is_active, created_at) "
            "VALUES ('订单未通过', :msg, :tid, 1, :ca)"
        ), {
            "msg": f"您的订单 #{order_id} 未通过审核。请联系管理员或核对转账信息后重新提交。",
            "tid": order[1], "ca": now
        })
        s.commit()
        return {"ok": True, "message": "已拒绝"}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()
