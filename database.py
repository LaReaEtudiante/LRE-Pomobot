# database.py

import aiosqlite
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# ─── RÉPERTOIRE & CHEMIN DB ────────────────────────────────────────────────────
DATA_DIR = os.getenv('POMOBOT_DATA_DIR', 'data')
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
DB_PATH = Path(DATA_DIR) / 'pomobot.db'

# ─── INITIALISATION & MIGRATION ────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Table participants (qui est actuellement en session)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            guild_id INTEGER,
            user_id  INTEGER,
            join_ts  REAL,
            mode     TEXT,
            PRIMARY KEY (guild_id, user_id)
        )
        """)

        # Table streaks (chaînes de jours consécutifs)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            guild_id INTEGER,
            user_id INTEGER,
            current_streak INTEGER DEFAULT 0,
            best_streak INTEGER DEFAULT 0,
            last_session_date TEXT,
            PRIMARY KEY (guild_id, user_id)
        )
        """)

        # Table stats (données de révision + colonnes étendues)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            guild_id  INTEGER,
            user_id   INTEGER,
            seconds   INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """)

        # Migration colonnes pour stats (ajout si manquant)
        cursor = await db.execute("PRAGMA table_info(stats)")
        cols = [r[1] for r in await cursor.fetchall()]
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

        # Table logs de sessions (historique détaillé)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS session_logs (
            guild_id   INTEGER,
            user_id    INTEGER,
            timestamp  REAL,
            mode       TEXT,
            duration   INTEGER,
            PRIMARY KEY (guild_id, user_id, timestamp, mode)
        )
        """)

        # Table settings (configuration serveur : maintenance, etc.)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY,
            maintenance_enabled INTEGER DEFAULT 0
        )
        """)

        await db.commit()

# ─── AJOUT / MISE À JOUR TEMPS ─────────────────────────────────────────────────
async def ajouter_temps(user_id: int, guild_id: int, seconds: int,
                        mode: str = '', is_session_end: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        # S'assurer que l’utilisateur existe
        await db.execute("""
            INSERT INTO stats(guild_id, user_id)
            VALUES(?, ?)
            ON CONFLICT(guild_id, user_id) DO NOTHING
        """, (guild_id, user_id))

        # Mise à jour temps
        await db.execute("""
            UPDATE stats
            SET seconds = seconds + ?,
                total_seconds = total_seconds + ?
            WHERE guild_id=? AND user_id=?
        """, (seconds, seconds, guild_id, user_id))

        if mode == 'A':
            await db.execute("UPDATE stats SET work_seconds_A = work_seconds_A + ? WHERE guild_id=? AND user_id=?",
                             (seconds, guild_id, user_id))
        elif mode == 'A_break':
            await db.execute("UPDATE stats SET break_seconds_A = break_seconds_A + ? WHERE guild_id=? AND user_id=?",
                             (seconds, guild_id, user_id))
        elif mode == 'B':
            await db.execute("UPDATE stats SET work_seconds_B = work_seconds_B + ? WHERE guild_id=? AND user_id=?",
                             (seconds, guild_id, user_id))
        elif mode == 'B_break':
            await db.execute("UPDATE stats SET break_seconds_B = break_seconds_B + ? WHERE guild_id=? AND user_id=?",
                             (seconds, guild_id, user_id))

        if is_session_end:
            await db.execute("UPDATE stats SET session_count = session_count + 1 WHERE guild_id=? AND user_id=?",
                             (guild_id, user_id))

        # Log session
        if mode in ('A', 'A_break', 'B', 'B_break') or is_session_end:
            ts = datetime.now(timezone.utc).timestamp()
            await db.execute("""
                INSERT OR IGNORE INTO session_logs
                (guild_id, user_id, timestamp, mode, duration)
                VALUES (?, ?, ?, ?, ?)
            """, (guild_id, user_id, ts, mode or '', seconds))

        await db.commit()

# ─── RÉCUPÉRATION D'UN UTILISATEUR ─────────────────────────────────────────────
async def recuperer_temps(user_id: int, guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT seconds, total_seconds, work_seconds_A, break_seconds_A,
                   work_seconds_B, break_seconds_B, session_count
            FROM stats WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if not row:
            return dict.fromkeys([
                'seconds','total_seconds',
                'work_seconds_A','break_seconds_A',
                'work_seconds_B','break_seconds_B',
                'session_count'
            ], 0)
        return {
            'seconds': row[0], 'total_seconds': row[1],
            'work_seconds_A': row[2], 'break_seconds_A': row[3],
            'work_seconds_B': row[4], 'break_seconds_B': row[5],
            'session_count': row[6]
        }

# ─── LISTES & CLASSEMENTS ──────────────────────────────────────────────────────
async def get_all_stats(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, seconds, total_seconds,
                   work_seconds_A, break_seconds_A,
                   work_seconds_B, break_seconds_B,
                   session_count
            FROM stats WHERE guild_id=?
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

# ─── PARTICIPANTS ──────────────────────────────────────────────────────────────
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
        cur = await db.execute("SELECT join_ts, mode FROM participants WHERE guild_id=? AND user_id=?",
                               (guild_id, user_id))
        row = await cur.fetchone()
        if not row:
            return None, None
        await db.execute("DELETE FROM participants WHERE guild_id=? AND user_id=?",
                         (guild_id, user_id))
        await db.commit()
        return row  # (join_ts, mode)

async def get_all_participants(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, mode FROM participants WHERE guild_id=?",
                               (guild_id,))
        return await cur.fetchall()

# ─── NOUVELLES MÉTRIQUES ───────────────────────────────────────────────────────
async def get_daily_totals(guild_id: int, days: int = 7) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"""
            SELECT date(datetime(timestamp, 'unixepoch', 'localtime')) AS day,
                   SUM(duration)
            FROM session_logs
            WHERE guild_id=?
              AND timestamp >= strftime('%s','now','-{days} days')
            GROUP BY day
            ORDER BY day
        """, (guild_id,))
        return await cur.fetchall()

async def get_weekly_sessions(guild_id: int, weeks: int = 4) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"""
            SELECT strftime('%Y-W%W', timestamp, 'unixepoch', 'localtime') AS yw,
                   COUNT(*)
            FROM session_logs
            WHERE guild_id=?
              AND timestamp >= strftime('%s','now','-{weeks} weeks')
            GROUP BY yw
            ORDER BY yw
        """, (guild_id,))
        return await cur.fetchall()

# ─── STREAKS ───────────────────────────────────────────────────────────────────
TIMEZONE = ZoneInfo("Europe/Zurich")

async def update_streak(guild_id: int, user_id: int):
    """Met à jour le streak après une session."""
    today = datetime.now(TIMEZONE).date()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT current_streak, best_streak, last_session_date FROM streaks WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()

        if row is None:
            await db.execute(
                "INSERT INTO streaks (guild_id, user_id, current_streak, best_streak, last_session_date) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, 1, 1, today.isoformat()),
            )
        else:
            current_streak, best_streak, last_date = row
            last_date = datetime.fromisoformat(last_date).date() if last_date else None

            if last_date == today:
                pass
            elif last_date == today - timedelta(days=1):
                current_streak += 1
                best_streak = max(best_streak, current_streak)
                await db.execute(
                    "UPDATE streaks SET current_streak=?, best_streak=?, last_session_date=? WHERE guild_id=? AND user_id=?",
                    (current_streak, best_streak, today.isoformat(), guild_id, user_id),
                )
            else:
                await db.execute(
                    "UPDATE streaks SET current_streak=?, last_session_date=? WHERE guild_id=? AND user_id=?",
                    (1, today.isoformat(), guild_id, user_id),
                )

        await db.commit()

async def get_streak(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT current_streak, best_streak FROM streaks WHERE guild_id=? AND user_id=?",
                               (guild_id, user_id))
        row = await cur.fetchone()
        return row if row else (0, 0)

async def top_streaks(guild_id: int, limit: int = 5):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, current_streak, best_streak
            FROM streaks
            WHERE guild_id=?
            ORDER BY current_streak DESC
            LIMIT ?
        """, (guild_id, limit))
        return await cur.fetchall()

# ─── PARAMÈTRES GLOBAUX ─────────────────────────────────────────────────────────
async def init_settings():
    """Créer la table settings si elle n'existe pas."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER PRIMARY KEY,
                maintenance_enabled INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def get_maintenance(guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT maintenance_enabled FROM settings WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return bool(row[0]) if row else False

async def set_maintenance(guild_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO settings(guild_id, maintenance_enabled)
            VALUES(?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET maintenance_enabled=excluded.maintenance_enabled
        """, (guild_id, int(enabled)))
        await db.commit()
