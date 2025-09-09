import aiosqlite
import os
from datetime import datetime, timezone
from pathlib import Path
import pytz

# ─── RÉPERTOIRE & CHEMIN DB ────────────────────────────────────────────────────
DATA_DIR = os.getenv('POMOBOT_DATA_DIR', 'data')
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
DB_PATH = Path(DATA_DIR) / 'pomobot.db'

# ─── INITIALISATION & MIGRATION ────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Table participants
        await db.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            guild_id INTEGER,
            user_id  INTEGER,
            join_ts  REAL,
            mode     TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")
        
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

        # Ancienne table stats
        await db.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            guild_id  INTEGER,
            user_id   INTEGER,
            seconds   INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Migration : ajout des nouvelles colonnes sans supprimer les données
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

        # Table de logs de sessions/phases
        await db.execute("""
        CREATE TABLE IF NOT EXISTS session_logs (
            guild_id   INTEGER,
            user_id    INTEGER,
            timestamp  REAL,
            mode       TEXT,
            duration   INTEGER,
            PRIMARY KEY (guild_id, user_id, timestamp, mode)
        )""")
        await db.commit()

# ─── AJOUT / MISE À JOUR DES TEMPS ─────────────────────────────────────────────
async def ajouter_temps(user_id: int, guild_id: int, seconds: int,
                        mode: str = None, is_session_end: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        # S'assurer de l'existence d'un enregistrement
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

        # Incrément de sessions
        if is_session_end:
            await db.execute("""
                UPDATE stats
                SET session_count = session_count + 1
                WHERE guild_id=? AND user_id=?
            """, (guild_id, user_id))

        # Enregistrement dans le log de session
        if mode in ('A', 'A_break', 'B', 'B_break') or is_session_end:
            ts = datetime.now(timezone.utc).timestamp()
            await db.execute("""
                INSERT OR IGNORE INTO session_logs
                (guild_id, user_id, timestamp, mode, duration)
                VALUES (?, ?, ?, ?, ?)
            """, (guild_id, user_id, ts, mode or '', seconds))

        await db.commit()

# ─── RÉCUPÉRATION D'UN UTILISATEUR ──────────────────────────────────────────────
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
            return dict.fromkeys([
                'seconds','total_seconds',
                'work_seconds_A','break_seconds_A',
                'work_seconds_B','break_seconds_B',
                'session_count'
            ], 0)
        return {
            'seconds':         row[0],
            'total_seconds':   row[1],
            'work_seconds_A':  row[2],
            'break_seconds_A': row[3],
            'work_seconds_B':  row[4],
            'break_seconds_B': row[5],
            'session_count':   row[6]
        }

# ─── LISTES & CLASSEMENTS ───────────────────────────────────────────────────────
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

# ─── PARTICIPANTS ───────────────────────────────────────────────────────────────
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

# ─── NOUVELLES MÉTRIQUES ────────────────────────────────────────────────────────
async def get_daily_totals(guild_id: int, days: int = 7) -> list:
    """
    Retourne [(date_iso, total_seconds), ...] pour les 'days' derniers jours.
    """
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
    """
    Retourne [(YYYY-Www, count), ...] pour les 'weeks' dernières semaines.
    """
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
# Fonction pour gérer les streaks ---------------------------------------------------------------------
TIMEZONE = pytz.timezone("Europe/Zurich")  # Fuseau horaire Lausanne

async def update_streak(guild_id: int, user_id: int):
    """Met à jour le streak d'un utilisateur après une session."""
    today = datetime.datetime.now(TIMEZONE).date()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT current_streak, best_streak, last_session_date FROM streaks WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()

        if row is None:
            # Première entrée pour cet utilisateur
            await db.execute(
                "INSERT INTO streaks (guild_id, user_id, current_streak, best_streak, last_session_date) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, 1, 1, today.isoformat()),
            )
        else:
            current_streak, best_streak, last_date = row
            last_date = datetime.date.fromisoformat(last_date) if last_date else None

            if last_date == today:
                # Déjà compté aujourd'hui, rien à faire
                pass
            elif last_date == today - datetime.timedelta(days=1):
                # Hier → on continue le streak
                current_streak += 1
                best_streak = max(best_streak, current_streak)
                await db.execute(
                    "UPDATE streaks SET current_streak=?, best_streak=?, last_session_date=? WHERE guild_id=? AND user_id=?",
                    (current_streak, best_streak, today.isoformat(), guild_id, user_id),
                )
            else:
                # Plus vieux → streak reset
                await db.execute(
                    "UPDATE streaks SET current_streak=?, last_session_date=? WHERE guild_id=? AND user_id=?",
                    (1, today.isoformat(), guild_id, user_id),
                )

        await db.commit()


async def get_streak(guild_id: int, user_id: int):
    """Récupère le streak actuel et le meilleur streak d'un utilisateur."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT current_streak, best_streak FROM streaks WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        return row if row else (0, 0)
import aiosqlite
import os
import datetime
import pytz
from pathlib import Path

# ─── RÉPERTOIRE & CHEMIN DB ────────────────────────────────────────────────────
DATA_DIR = os.getenv("POMOBOT_DATA_DIR", "data")
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
DB_PATH = Path(DATA_DIR) / "pomobot.db"

# Fuseau horaire Lausanne
TIMEZONE = pytz.timezone("Europe/Zurich")


# ─── INITIALISATION ───────────────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Participants en cours
        await db.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            guild_id INTEGER,
            user_id  INTEGER,
            join_ts  REAL,
            mode     TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Stats globales
        await db.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            guild_id        INTEGER,
            user_id         INTEGER,
            total_seconds   INTEGER DEFAULT 0,
            work_seconds_A  INTEGER DEFAULT 0,
            break_seconds_A INTEGER DEFAULT 0,
            work_seconds_B  INTEGER DEFAULT 0,
            break_seconds_B INTEGER DEFAULT 0,
            session_count   INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )""")

        # Logs de sessions
        await db.execute("""
        CREATE TABLE IF NOT EXISTS session_logs (
            guild_id   INTEGER,
            user_id    INTEGER,
            timestamp  REAL,
            mode       TEXT,
            duration   INTEGER,
            PRIMARY KEY (guild_id, user_id, timestamp, mode)
        )""")

        # Streaks
        await db.execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            guild_id          INTEGER,
            user_id           INTEGER,
            current_streak    INTEGER DEFAULT 0,
            best_streak       INTEGER DEFAULT 0,
            last_session_date TEXT,
            PRIMARY KEY (guild_id, user_id)
        )""")

        await db.commit()


# ─── AJOUT / MISE À JOUR DES TEMPS ─────────────────────────────────────────────
async def ajouter_temps(user_id: int, guild_id: int, seconds: int,
                        mode: str = None, is_session_end: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        # S'assurer que l'utilisateur existe
        await db.execute("""
            INSERT INTO stats (guild_id, user_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id, user_id) DO NOTHING
        """, (guild_id, user_id))

        # Mise à jour du total global
        await db.execute("""
            UPDATE stats
            SET total_seconds = total_seconds + ?
            WHERE guild_id=? AND user_id=?
        """, (seconds, guild_id, user_id))

        # Travail vs pause A/B
        if mode == "A":
            await db.execute("UPDATE stats SET work_seconds_A = work_seconds_A + ? WHERE guild_id=? AND user_id=?",
                             (seconds, guild_id, user_id))
        elif mode == "A_break":
            await db.execute("UPDATE stats SET break_seconds_A = break_seconds_A + ? WHERE guild_id=? AND user_id=?",
                             (seconds, guild_id, user_id))
        elif mode == "B":
            await db.execute("UPDATE stats SET work_seconds_B = work_seconds_B + ? WHERE guild_id=? AND user_id=?",
                             (seconds, guild_id, user_id))
        elif mode == "B_break":
            await db.execute("UPDATE stats SET break_seconds_B = break_seconds_B + ? WHERE guild_id=? AND user_id=?",
                             (seconds, guild_id, user_id))

        # Incrément de sessions
        if is_session_end:
            await db.execute("""
                UPDATE stats
                SET session_count = session_count + 1
                WHERE guild_id=? AND user_id=?
            """, (guild_id, user_id))

        # Log de session
        if mode or is_session_end:
            ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
            await db.execute("""
                INSERT OR IGNORE INTO session_logs
                (guild_id, user_id, timestamp, mode, duration)
                VALUES (?, ?, ?, ?, ?)
            """, (guild_id, user_id, ts, mode or "", seconds))

        await db.commit()


# ─── RÉCUPÉRATION D'UN UTILISATEUR ──────────────────────────────────────────────
async def recuperer_temps(user_id: int, guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT total_seconds, work_seconds_A, break_seconds_A,
                   work_seconds_B, break_seconds_B, session_count
            FROM stats
            WHERE guild_id=? AND user_id=?
        """, (guild_id, user_id))
        row = await cur.fetchone()
        if not row:
            return dict.fromkeys([
                "total_seconds", "work_seconds_A", "break_seconds_A",
                "work_seconds_B", "break_seconds_B", "session_count"
            ], 0)
        return {
            "total_seconds":   row[0],
            "work_seconds_A":  row[1],
            "break_seconds_A": row[2],
            "work_seconds_B":  row[3],
            "break_seconds_B": row[4],
            "session_count":   row[5],
        }


# ─── LISTES & CLASSEMENTS ───────────────────────────────────────────────────────
async def get_all_stats(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT user_id, total_seconds, work_seconds_A, break_seconds_A,
                   work_seconds_B, break_seconds_B, session_count
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


# ─── PARTICIPANTS ───────────────────────────────────────────────────────────────
async def add_participant(user_id: int, guild_id: int, mode: str):
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO participants (guild_id, user_id, join_ts, mode)
            VALUES (?, ?, ?, ?)
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
        await db.execute("DELETE FROM participants WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await db.commit()
        return row


async def get_all_participants(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, mode FROM participants WHERE guild_id=?", (guild_id,))
        return await cur.fetchall()


# ─── NOUVELLES MÉTRIQUES ────────────────────────────────────────────────────────
async def get_daily_totals(guild_id: int, days: int = 7) -> list:
    """Retourne [(date_iso, total_seconds), ...] pour les X derniers jours."""
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
    """Retourne [(YYYY-Www, count), ...] pour les X dernières semaines."""
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


# ─── STREAKS ────────────────────────────────────────────────────────────────────
async def update_streak(guild_id: int, user_id: int):
    """Met à jour le streak d'un utilisateur après une session."""
    today = datetime.datetime.now(TIMEZONE).date()
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
            last_date = datetime.date.fromisoformat(last_date) if last_date else None

            if last_date == today:
                pass
            elif last_date == today - datetime.timedelta(days=1):
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
    """Retourne (current_streak, best_streak)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT current_streak, best_streak FROM streaks WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
        return row if row else (0, 0)


async def top_streaks(guild_id: int, limit: int = 5):
    """Retourne le top des streaks (triés par streak actuel puis meilleur streak)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, current_streak, best_streak FROM streaks WHERE guild_id=? ORDER BY current_streak DESC, best_streak DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cursor.fetchall()


async def top_streaks(guild_id: int, limit: int = 5):
    """Retourne le top des streaks pour un serveur."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, current_streak, best_streak FROM streaks WHERE guild_id=? ORDER BY current_streak DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cursor.fetchall()
