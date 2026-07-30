"""
Database — MySQL (pymysql), 12 tables, 6 categories x 2 (index + detail)
world / map / rule / character / item / memory
"""

import json, os
from typing import Optional
from sqlalchemy import create_engine, text, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

# ── Config ──────────────────────────────────────────────
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.environ.get("MYSQL_PORT", "3306")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASS = os.environ.get("MYSQL_PASS")
if not MYSQL_PASS:
    raise RuntimeError("MYSQL_PASS 环境变量未设置")
MYSQL_DB   = os.environ.get("MYSQL_DB", "fenli")
DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASS}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"

CATEGORIES = ["world", "map", "rule", "character", "item"]
CATEGORY_TABLES = {c: f"{c}_library" for c in CATEGORIES}
DETAIL_TABLES   = {c: f"{c}_detail_library" for c in CATEGORIES}
CATEGORY_TABLES["memory"] = "memory_library"
DETAIL_TABLES["memory"]   = "memory_detail_library"

# ── ORM ─────────────────────────────────────────────────
class Base(DeclarativeBase): pass

class WorldLib(Base):      __tablename__="world_library";      player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_hint:Mapped[str]=mapped_column(Text)
class WorldDtl(Base):      __tablename__="world_detail_library"; player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_detail:Mapped[str]=mapped_column(Text)
class MapLib(Base):        __tablename__="map_library";        player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_hint:Mapped[str]=mapped_column(Text)
class MapDtl(Base):        __tablename__="map_detail_library";  player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_detail:Mapped[str]=mapped_column(Text)
class RuleLib(Base):       __tablename__="rule_library";       player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_hint:Mapped[str]=mapped_column(Text)
class RuleDtl(Base):       __tablename__="rule_detail_library"; player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_detail:Mapped[str]=mapped_column(Text)
class CharLib(Base):       __tablename__="character_library";  player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_hint:Mapped[str]=mapped_column(Text)
class CharDtl(Base):       __tablename__="character_detail_library"; player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_detail:Mapped[str]=mapped_column(Text)
class ItemLib(Base):       __tablename__="item_library";       player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_hint:Mapped[str]=mapped_column(Text)
class ItemDtl(Base):       __tablename__="item_detail_library"; player_id:Mapped[str]=mapped_column(String(255),primary_key=True); tag_name:Mapped[str]=mapped_column(String(255),primary_key=True); tag_detail:Mapped[str]=mapped_column(Text)
class MemLib(Base):        __tablename__="memory_library";     player_id:Mapped[str]=mapped_column(String(255),primary_key=True); memory_id:Mapped[str]=mapped_column(String(255),primary_key=True); memory_hint:Mapped[str]=mapped_column(Text)
class MemDtl(Base):        __tablename__="memory_detail_library"; player_id:Mapped[str]=mapped_column(String(255),primary_key=True); memory_id:Mapped[str]=mapped_column(String(255),primary_key=True); memory_detail:Mapped[str]=mapped_column(Text)
class SaveSlot(Base):      __tablename__="save_slots"; id:Mapped[int]=mapped_column(primary_key=True,autoincrement=True); player_id:Mapped[str]=mapped_column(String(255)); slot_name:Mapped[str]=mapped_column(String(255)); turn_number:Mapped[int]=mapped_column(); save_data:Mapped[str]=mapped_column(Text); is_auto:Mapped[bool]=mapped_column(default=False); created_at:Mapped[str]=mapped_column(String(50))
class ReviewLog(Base):     __tablename__="review_logs"; id:Mapped[int]=mapped_column(primary_key=True,autoincrement=True); target_type:Mapped[str]=mapped_column(String(32)); target_id:Mapped[str]=mapped_column(String(255)); content:Mapped[str]=mapped_column(Text,nullable=True); result:Mapped[str]=mapped_column(String(20)); created_at:Mapped[str]=mapped_column(String(50))

# ── Engine ──────────────────────────────────────────────
engine = None; SessionLocal: sessionmaker = None
def init_db(url=None):
    global engine, SessionLocal
    engine = create_engine(url or DATABASE_URL, echo=False, pool_size=5, pool_recycle=3600)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
def get_session() -> Session: return SessionLocal()

def _j(d): return json.dumps(d, ensure_ascii=False)
def _l(s): return json.loads(s)

IU_SQL = "INSERT INTO {t} VALUES (:pid,:tn,:th) ON DUPLICATE KEY UPDATE tag_hint=VALUES(tag_hint)"
IU_DTL = "INSERT INTO {t} VALUES (:pid,:tn,:td) ON DUPLICATE KEY UPDATE tag_detail=VALUES(tag_detail)"

# ── DAO ─────────────────────────────────────────────────
class TagDAO:
    """Unified tag DAO - routes to correct table by category"""
    def __init__(self, s: Session, pid: str): self.s = s; self.pid = pid

    def _tbl(self, cat: str): return CATEGORY_TABLES.get(cat, f"{cat}_library")
    def _dtl(self, cat: str): return DETAIL_TABLES.get(cat, f"{cat}_detail_library")

    def all_hints(self) -> list[dict]:
        """Union all categories for AI-1"""
        rows = []
        for cat in CATEGORIES:
            t = self._tbl(cat)
            r = self.s.execute(text(f"SELECT tag_name,tag_hint FROM {t} WHERE player_id=:pid"), {"pid":self.pid})
            for row in r: rows.append({"tag_name":row[0],"tag_hint":row[1],"category":cat})
        return rows

    def hints_by_category(self) -> dict[str,list[dict]]:
        result = {}
        for cat in CATEGORIES:
            t = self._tbl(cat)
            r = self.s.execute(text(f"SELECT tag_name,tag_hint FROM {t} WHERE player_id=:pid"), {"pid":self.pid})
            result[cat] = [{"tag_name":row[0],"tag_hint":row[1]} for row in r]
        return result

    def get_detail(self, cat: str, tn: str) -> Optional[dict]:
        dt = self._dtl(cat)
        r = self.s.execute(text(f"SELECT tag_detail FROM {dt} WHERE player_id=:pid AND tag_name=:tn"), {"pid":self.pid,"tn":tn})
        row = r.fetchone(); return _l(row[0]) if row else None

    def multi_detail(self, cat: str, tns: list[str]) -> dict[str,dict]:
        if not tns: return {}
        dt = self._dtl(cat)
        ph = ",".join([f":t{i}" for i in range(len(tns))])
        p = {"pid":self.pid}
        for i,tn in enumerate(tns): p[f"t{i}"]=tn
        r = self.s.execute(text(f"SELECT tag_name,tag_detail FROM {dt} WHERE player_id=:pid AND tag_name IN ({ph})"), p)
        return {row[0]:_l(row[1]) for row in r}

    def multi_detail_by_category(self, fetch_map: dict[str,list[str]]) -> dict[str,dict[str,dict]]:
        """fetch_map: {category: [tag_names]} -> {category: {tag_name: detail}}"""
        result = {}
        for cat, tns in fetch_map.items():
            if tns: result[cat] = self.multi_detail(cat, tns)
        return result

    def exists(self, cat: str, tn: str) -> bool:
        t = self._tbl(cat)
        r = self.s.execute(text(f"SELECT 1 FROM {t} WHERE player_id=:pid AND tag_name=:tn"), {"pid":self.pid,"tn":tn})
        return r.fetchone() is not None

    def create(self, cat: str, tn: str, th: str, td: dict):
        t, dt = self._tbl(cat), self._dtl(cat)
        self.s.execute(text(IU_SQL.format(t=t)), {"pid":self.pid,"tn":tn,"th":th})
        self.s.execute(text(IU_DTL.format(t=dt)), {"pid":self.pid,"tn":tn,"td":_j(td)})

    def update(self, cat: str, tn: str, td: dict):
        dt = self._dtl(cat)
        self.s.execute(text(f"UPDATE {dt} SET tag_detail=:td WHERE player_id=:pid AND tag_name=:tn"), {"pid":self.pid,"tn":tn,"td":_j(td)})

    def count_by_category(self) -> dict[str,int]:
        c = {}
        for cat in CATEGORIES:
            t = self._tbl(cat)
            r = self.s.execute(text(f"SELECT COUNT(*) FROM {t} WHERE player_id=:pid"), {"pid":self.pid})
            c[cat] = r.fetchone()[0]
        r = self.s.execute(text("SELECT COUNT(*) FROM memory_library WHERE player_id=:pid"),{"pid":self.pid})
        c["memory"] = r.fetchone()[0]
        return c

    def counts(self) -> dict[str,int]: return self.count_by_category()

class SaveDAO:
    """存档 CRUD"""
    def __init__(self, s: Session, pid: str): self.s = s; self.pid = pid
    def list(self, limit=20):
        r = self.s.execute(text("SELECT id,slot_name,turn_number,is_auto,created_at FROM save_slots WHERE player_id=:pid ORDER BY created_at DESC LIMIT :lim"), {"pid":self.pid,"lim":limit})
        return [{"id":row[0],"slot_name":row[1],"turn_number":row[2],"is_auto":bool(row[3]),"created_at":row[4]} for row in r]
    def get(self, sid):
        r = self.s.execute(text("SELECT save_data FROM save_slots WHERE id=:id AND player_id=:pid"), {"id":sid,"pid":self.pid})
        row = r.fetchone(); return _l(row[0]) if row else None
    def save(self, slot_name, turn_number, data, is_auto=False):
        now = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.s.execute(text("INSERT INTO save_slots (player_id,slot_name,turn_number,save_data,is_auto,created_at) VALUES (:pid,:sn,:tn,:sd,:ia,:ca)"), {"pid":self.pid,"sn":slot_name,"tn":turn_number,"sd":_j(data),"ia":is_auto,"ca":now})
    def delete(self, sid):
        self.s.execute(text("DELETE FROM save_slots WHERE id=:id AND player_id=:pid"), {"id":sid,"pid":self.pid})
    def count(self):
        r = self.s.execute(text("SELECT COUNT(*) FROM save_slots WHERE player_id=:pid"), {"pid":self.pid})
        return r.fetchone()[0]
    def auto_clean(self, keep=10):
        """保留最近N个自动存档，删更旧的"""
        r = self.s.execute(text("SELECT id FROM save_slots WHERE player_id=:pid AND is_auto=1 ORDER BY created_at DESC"), {"pid":self.pid})
        ids = [row[0] for row in r]
        for sid in ids[keep:]: self.delete(sid)

class CloudDAO:
    """云端共享副本 CRUD"""
    def __init__(self, s: Session): self.s = s
    def list_all(self, limit=20):
        r = self.s.execute(text("SELECT id,uploader_id,title,description,tags,downloads,created_at,avg_rating,rating_count,play_count,cover_image,opening_monologue FROM shared_copies ORDER BY downloads DESC LIMIT :lim"), {"lim":limit})
        return [{"id":row[0],"uploader_id":row[1],"title":row[2],"desc":row[3],"tags":row[4],"downloads":row[5],"created_at":row[6],"avg_rating":float(row[7] or 0),"rating_count":int(row[8] or 0),"play_count":int(row[9] or 0),"cover_image":row[10] or "","opening_monologue":row[11] or ""} for row in r]
    def get(self, sid):
        r = self.s.execute(text("SELECT save_data FROM shared_copies WHERE id=:id"), {"id":sid})
        row = r.fetchone(); return _l(row[0]) if row else None
    def upload(self, uploader_id, title, desc, tags_str, save_data):
        now = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.s.execute(text("INSERT INTO shared_copies (uploader_id,title,description,tags,save_data,created_at) VALUES (:uid,:t,:d,:tg,:sd,:ca)"), {"uid":uploader_id,"t":title,"d":desc,"tg":tags_str,"sd":_j(save_data),"ca":now})
    def download_count(self, sid):
        self.s.execute(text("UPDATE shared_copies SET downloads=downloads+1 WHERE id=:id"), {"id":sid})
    def delete(self, sid, uploader_id):
        self.s.execute(text("DELETE FROM shared_copies WHERE id=:id AND uploader_id=:uid"), {"id":sid,"uid":uploader_id})

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


class MemoryDAO:
    def __init__(self, s: Session, pid: str): self.s = s; self.pid = pid
    def all_hints(self) -> list[dict]:
        r = self.s.execute(text("SELECT memory_id,memory_hint FROM memory_library WHERE player_id=:pid ORDER BY memory_id"), {"pid":self.pid})
        return [{"memory_id":row[0],"memory_hint":row[1]} for row in r]
    def multi_detail(self, mids: list[str]) -> dict[str,dict]:
        if not mids: return {}
        ph=",".join([f":m{i}" for i in range(len(mids))])
        p={"pid":self.pid}
        for i,mid in enumerate(mids): p[f"m{i}"]=mid
        r=self.s.execute(text(f"SELECT memory_id,memory_detail FROM memory_detail_library WHERE player_id=:pid AND memory_id IN ({ph})"), p)
        return {row[0]:_l(row[1]) for row in r}
    def create(self, mid, mh, md):
        self.s.execute(text("INSERT INTO memory_library (player_id,memory_id,memory_hint) VALUES (:pid,:mid,:mh) ON DUPLICATE KEY UPDATE memory_hint=VALUES(memory_hint)"), {"pid":self.pid,"mid":mid,"mh":mh})
        self.s.execute(text("INSERT INTO memory_detail_library (player_id,memory_id,memory_detail) VALUES (:pid,:mid,:md) ON DUPLICATE KEY UPDATE memory_detail=VALUES(memory_detail)"), {"pid":self.pid,"mid":mid,"md":_j(md)})

# ── 速率限制工具 ─────────────────────────────────────────
import time as _time
_RATE_LIMIT_STORE = {}  # key -> list of timestamps

def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """检查速率限制。返回 True 表示允许，False 表示超限"""
    now = _time.time()
    window_start = now - window_seconds
    if key not in _RATE_LIMIT_STORE:
        _RATE_LIMIT_STORE[key] = []
    # 清理过期记录
    _RATE_LIMIT_STORE[key] = [t for t in _RATE_LIMIT_STORE[key] if t > window_start]
    if len(_RATE_LIMIT_STORE[key]) >= max_requests:
        return False
    _RATE_LIMIT_STORE[key].append(now)
    return True
