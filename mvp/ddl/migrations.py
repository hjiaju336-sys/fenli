"""DDL建表/迁移 — 从 server.py 提取"""
import os
import time
import bcrypt

from sqlalchemy import text
from db import get_session


def _hash(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _ensure_user_table():
    s = get_session()
    s.execute(text(
        "CREATE TABLE IF NOT EXISTS users ("
        "player_id VARCHAR(255) PRIMARY KEY, "
        "username VARCHAR(255) UNIQUE, "
        "password_hash VARCHAR(255), "
        "created_at VARCHAR(50))"
    ))
    # 仅在 ADMIN_PASSWORD 环境变量存在时创建管理员
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if admin_pw:
        existing = s.execute(text("SELECT 1 FROM users WHERE username='admin'")).fetchone()
        if not existing:
            s.execute(text(
                "INSERT INTO users (player_id,username,password_hash,created_at,is_admin) "
                "VALUES (:pid,:un,:pw,:ca,1)"
            ), {"pid": "u001", "un": "admin", "pw": _hash(admin_pw), "ca": "2026-01-01"})
    s.commit()
    s.close()


def _ensure_phase3_tables():
    s = get_session()
    # 积分账户
    s.execute(text("""CREATE TABLE IF NOT EXISTS point_accounts (
        player_id VARCHAR(255) PRIMARY KEY,
        balance INT DEFAULT 0,
        total_earned INT DEFAULT 0,
        total_spent INT DEFAULT 0,
        sign_in_streak INT DEFAULT 0,
        last_sign_in_date VARCHAR(20),
        created_at VARCHAR(50)
    )"""))
    # 积分流水
    s.execute(text("""CREATE TABLE IF NOT EXISTS point_transactions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        player_id VARCHAR(255),
        amount INT,
        reason VARCHAR(100),
        ref_id VARCHAR(255),
        created_at VARCHAR(50)
    )"""))
    # 兑换码
    s.execute(text("""CREATE TABLE IF NOT EXISTS exchange_codes (
        code VARCHAR(64) PRIMARY KEY,
        points INT,
        batch_id VARCHAR(64),
        created_by VARCHAR(255),
        used_by VARCHAR(255) DEFAULT NULL,
        used_at VARCHAR(50) DEFAULT NULL,
        is_used TINYINT DEFAULT 0,
        created_at VARCHAR(50)
    )"""))
    # 模板评分
    s.execute(text("""CREATE TABLE IF NOT EXISTS template_ratings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        target_type VARCHAR(32),
        target_id VARCHAR(255),
        player_id VARCHAR(255),
        rating TINYINT,
        created_at VARCHAR(50),
        UNIQUE KEY uk_rate (target_type, target_id, player_id)
    )"""))
    # 模板评论
    s.execute(text("""CREATE TABLE IF NOT EXISTS template_comments (
        id INT AUTO_INCREMENT PRIMARY KEY,
        target_type VARCHAR(32),
        target_id VARCHAR(255),
        player_id VARCHAR(255),
        username VARCHAR(255),
        content TEXT,
        parent_id INT DEFAULT NULL,
        likes INT DEFAULT 0,
        is_approved TINYINT DEFAULT 1,
        created_at VARCHAR(50)
    )"""))
    # 评论点赞
    s.execute(text("""CREATE TABLE IF NOT EXISTS comment_likes (
        comment_id INT,
        player_id VARCHAR(255),
        PRIMARY KEY (comment_id, player_id)
    )"""))
    # 评论举报
    s.execute(text("""CREATE TABLE IF NOT EXISTS comment_reports (
        id INT AUTO_INCREMENT PRIMARY KEY,
        comment_id INT,
        reporter_id VARCHAR(255),
        reason VARCHAR(500),
        is_resolved TINYINT DEFAULT 0,
        resolved_by VARCHAR(255),
        created_at VARCHAR(50)
    )"""))
    # 玩家建议
    s.execute(text("""CREATE TABLE IF NOT EXISTS suggestions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        player_id VARCHAR(255),
        username VARCHAR(255),
        category VARCHAR(50),
        content TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        admin_reply TEXT,
        created_at VARCHAR(50)
    )"""))
    # 系统公告
    s.execute(text("""CREATE TABLE IF NOT EXISTS system_announcements (
        id INT AUTO_INCREMENT PRIMARY KEY,
        content TEXT,
        created_by VARCHAR(255),
        is_active TINYINT DEFAULT 1,
        created_at VARCHAR(50)
    )"""))
    # 系统配置
    s.execute(text("""CREATE TABLE IF NOT EXISTS system_config (
        key_name VARCHAR(100) PRIMARY KEY,
        value VARCHAR(500),
        updated_at VARCHAR(50)
    )"""))
    # 默认系统配置（注册赠送积分）
    existing = s.execute(text(
        "SELECT 1 FROM system_config WHERE key_name='register_bonus'"
    )).fetchone()
    if not existing:
        s.execute(text(
            "INSERT INTO system_config (key_name,value,updated_at) VALUES (:k,:v,:u)"
        ), {"k": "register_bonus", "v": "200", "u": "2026-01-01"})
    # ALTER users 表加字段
    for col, typ in [
        ("is_admin", "TINYINT DEFAULT 0"),
        ("avatar_url", "VARCHAR(500)"),
        ("is_banned", "TINYINT DEFAULT 0"),
    ]:
        try:
            s.execute(text(f"ALTER TABLE users ADD COLUMN {col} {typ}"))
        except Exception as e:
            print(f"[Phase3] ALTER users.{col} skipped: {e}")
    # ALTER comment_reports 加唯一约束
    try:
        s.execute(text(
            "ALTER TABLE comment_reports ADD UNIQUE KEY uk_report (comment_id, reporter_id)"
        ))
    except Exception as e:
        print(f"[Phase3] ALTER comment_reports.uk_report skipped: {e}")
    # 创建 shared_copies 表（如果不存在）
    s.execute(text("""CREATE TABLE IF NOT EXISTS shared_copies (
        id INT AUTO_INCREMENT PRIMARY KEY,
        uploader_id VARCHAR(255),
        title VARCHAR(255),
        description TEXT,
        tags TEXT,
        save_data TEXT,
        downloads INT DEFAULT 0,
        created_at VARCHAR(50),
        cover_image VARCHAR(500),
        opening_monologue TEXT,
        avg_rating FLOAT DEFAULT 0,
        rating_count INT DEFAULT 0,
        play_count INT DEFAULT 0
    )"""))
    # ALTER shared_copies 表加字段
    for col, typ in [
        ("cover_image", "VARCHAR(500)"),
        ("opening_monologue", "TEXT"),
        ("avg_rating", "FLOAT DEFAULT 0"),
        ("rating_count", "INT DEFAULT 0"),
        ("play_count", "INT DEFAULT 0"),
    ]:
        try:
            s.execute(text(f"ALTER TABLE shared_copies ADD COLUMN {col} {typ}"))
        except Exception as e:
            print(f"[Phase3] ALTER shared_copies.{col} skipped: {e}")
    s.commit()
    s.close()


def _ensure_hook_tables():
    """创建Hook事件系统相关表"""
    s = get_session()
    try:
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS player_achievements (
                id INT AUTO_INCREMENT PRIMARY KEY,
                player_id VARCHAR(255),
                achievement_key VARCHAR(255),
                achievement_name VARCHAR(255),
                icon VARCHAR(10),
                scenario_name VARCHAR(255),
                unlocked_at VARCHAR(50),
                UNIQUE KEY uk_ach (player_id, achievement_key)
            )
        """))
        s.commit()
    except Exception as e:
        print(f"[HookTables] Error: {e}")
    finally:
        s.close()
