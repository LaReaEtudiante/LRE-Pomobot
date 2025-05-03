import aiosqlite
from datetime import datetime, timezone
import os
from pathlib import Path

# ─── RÉPERTOIRE DE DONNÉES ─────────────────────────────────────────────────────
DATA_DIR = os.getenv('POMOBOTOB_DATA_DIR', 'data')
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
DB_PATH = Path(DATA_DIR) / 'pomobot.db'

# ─── INITIALISATION DE LA BASE ─────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            guild_id INTEGER,
            user_id  INTEGER,
            seconds  INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            guild_id INTEGER,
            user_id  INTEGER,
            join_ts  REAL,
            mode     TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")
        await db.commit()

# ─── STATISTIQUES ──────────────────────────────────────────────────────────────
async def ajouter_temps(user_id: int, guild_id: int, seconds: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
          INSERT INTO stats (guild_id, user_id, seconds)
          VALUES (?, ?, ?)
          ON CONFLICT(guild_id, user_id) DO UPDATE
            SET seconds = seconds + excluded.seconds
        """, (guild_id, user_id, seconds))
        await db.commit()

async def recuperer_temps(user_id: int, guild_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT seconds FROM stats WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        )
        row = await cur.fetchone()
        return row[0] if row else 0

async def get_all_stats(guild_id: int):
    """Retourne la liste [(user_id, seconds), …] pour un serveur."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, seconds FROM stats WHERE guild_id=?",
            (guild_id,)
        )
        return await cur.fetchall()

async def classement_top10(guild_id: int):
    """Top 10 utilisateurs par secondes cumulées."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, seconds FROM stats WHERE guild_id=? ORDER BY seconds DESC LIMIT 10",
            (guild_id,)
        )
        return await cur.fetchall()  # [(user_id, seconds), ...]

# ─── PARTICIPANTS EN SESSION ───────────────────────────────────────────────────
async def add_participant(user_id: int, guild_id: int, mode: str):
    now = datetime.now(timezone.utc).timestamp()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
          INSERT INTO participants (guild_id, user_id, join_ts, mode)
          VALUES (?, ?, ?, ?)
          ON CONFLICT(guild_id, user_id) DO UPDATE
            SET join_ts = excluded.join_ts, mode = excluded.mode
        """, (guild_id, user_id, now, mode))
        await db.commit()

async def remove_participant(user_id: int, guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT join_ts, mode FROM participants WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        )
        row = await cur.fetchone()
        if not row:
            return None, None
        await db.execute(
            "DELETE FROM participants WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        )
        await db.commit()
        return row  # (join_ts, mode)

async def get_all_participants(guild_id: int):
    """Retourne la liste [(user_id, mode), …] inscrits."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, mode FROM participants WHERE guild_id=?",
            (guild_id,)
        )
        return await cur.fetchall()
