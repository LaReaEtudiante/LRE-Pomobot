import aiosqlite
import os
from datetime import datetime, timezone
from pathlib import Path

# Dossier et chemin de base de données
DATA_DIR = os.getenv('POMOBOT_DATA_DIR', 'data')
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
DB_PATH = Path(DATA_DIR) / 'pomobot.db'

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Table des participants
        await db.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            guild_id INTEGER,
            user_id  INTEGER,
            join_ts  REAL,
            mode     TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Table stats ancienne structure
        await db.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            guild_id  INTEGER,
            user_id   INTEGER,
            seconds   INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Migration : ajout des nouvelles colonnes sans perte de données
        cursor = await db.execute("PRAGMA table_info(stats)")
        cols = [row[1] for row in await cursor.fetchall()]
        migrations = {
            'total_seconds':   'INTEGER DEFAULT 0',
            'work_seconds_A':  'INTEGER DEFAULT 0',
            'break_seconds_A': 'INTEGER DEFAULT 0',
            'work_seconds_B':  'INTEGER DEFAULT 0',
            'break_seconds_B': 'INTEGER DEFAULT 0',
            'session_count':   'INTEGER DEFAULT 0'
        }
        for col, definition in migrations.items():
            if col not in cols:
                await db.execute(f"ALTER TABLE stats ADD COLUMN {col} {definition}")

        await db.commit()

async def ajouter_temps(user_id: int, guild_id: int, seconds: int,
                        mode: str = None, is_session_end: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        # S’assurer que la ligne existe
        await db.execute("""
            INSERT INTO stats(guild_id, user_id)
            VALUES(?, ?)
            ON CONFLICT(guild_id, user_id) DO NOTHING
        """, (guild_id, user_id))

        # Mise à jour du total global
        await db.execute("""
            UPDATE stats
            SET seconds = seconds + ?,
                total_seconds = total_seconds + ?
            WHERE guild_id=? AND user_id=?
        """, (seconds, seconds, guild_id, user_id))

        # Travail vs pause A/B
        if mode == 'A':
            await db.execute("""
                UPDATE stats
                SET work_seconds_A = work_seconds_A + ?
                WHERE guild_id=? AND user_id=?
            """, (seconds, guild_id, user_id))
        elif mode == 'A_break':
            await db.execute("""
                UPDATE stats
                SET break_seconds_A = break_seconds_A + ?
                WHERE guild_id=? AND user_id=?
            """, (seconds, guild_id, user_id))
        elif mode == 'B':
            await db.execute("""
                UPDATE stats
                SET work_seconds_B = work_seconds_B + ?
                WHERE guild_id=? AND user_id=?
            """, (seconds, guild_id, user_id))
        elif mode == 'B_break':
            await db.execute("""
                UPDATE stats
                SET break_seconds_B = break_seconds_B + ?
                WHERE guild_id=? AND user_id=?
            """, (seconds, guild_id, user_id))

        # Incrémenter le nombre de sessions si fin de session
        if is_session_end:
            await db.execute("""
                UPDATE stats
                SET session_count = session_count + 1
                WHERE guild_id=? AND user_id=?
            """, (guild_id, user_id))

        await db.commit()

async def recuperer_temps(user_id: int, guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT seconds, total_seconds, work_seconds_A, break_seconds_A,
                   work_seconds_B, break_seconds_B, session_count
            FROM stats
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if not row:
            return {
                'seconds': 0,
                'total_seconds': 0,
                'work_seconds_A': 0,
                'break_seconds_A': 0,
                'work_seconds_B': 0,
                'break_seconds_B': 0,
                'session_count': 0
            }
        return {
            'seconds':         row[0],
            'total_seconds':   row[1],
            'work_seconds_A':  row[2],
            'break_seconds_A': row[3],
            'work_seconds_B':  row[4],
            'break_seconds_B': row[5],
            'session_count':   row[6]
        }

async def get_all_stats(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, seconds, total_seconds,
                   work_seconds_A, break_seconds_A,
                   work_seconds_B, break_seconds_B,
                   session_count
            FROM stats
            WHERE guild_id=?
        """, (guild_id,))
        return await cur.fetchall()

async def classement_top10(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, total_seconds
            FROM stats
            WHERE guild_id=?
            ORDER BY total_seconds DESC
            LIMIT 10
        """, (guild_id,))
        return await cur.fetchall()

async def add_participant(user_id: int, guild_id: int, mode: str):
    now = datetime.now(timezone.utc).timestamp()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO participants(guild_id, user_id, join_ts, mode)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE
              SET join_ts=excluded.join_ts, mode=excluded.mode
        """, (guild_id, user_id, now, mode))
        await db.commit()

async def remove_participant(user_id: int, guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT join_ts, mode FROM participants
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if not row:
            return None, None
        await db.execute("""
            DELETE FROM participants
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        await db.commit()
        return row  # (join_ts, mode)

async def get_all_participants(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, mode FROM participants
            WHERE guild_id=?
        """, (guild_id,))
        return await cur.fetchall()
