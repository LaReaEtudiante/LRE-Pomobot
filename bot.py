# bot.py

# ─── IMPORTS ──────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
import os, sys, asyncio, logging
import discord
from discord.ext import commands, tasks
import configparser
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
import messages
from database import (
    DB_PATH,
    init_db,
    ajouter_temps,
    get_all_stats,
    add_participant,
    remove_participant,
    get_all_participants,
    get_daily_totals,
    get_weekly_sessions,
    update_streak,
    get_streak,
    top_streaks,
)

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
load_dotenv()
config = configparser.ConfigParser()
config.read('settings.ini')

TOKEN               = os.getenv('DISCORD_TOKEN')
WORK_TIME_A         = config['CURRENT_SETTINGS'].getint('work_time_A', fallback=50)
BREAK_TIME_A        = config['CURRENT_SETTINGS'].getint('break_time_A', fallback=10)
POMO_ROLE_A         = config['CURRENT_SETTINGS'].get('pomodoro_role_A', fallback='50-10')
WORK_TIME_B         = config['CURRENT_SETTINGS'].getint('work_time_B', fallback=25)
BREAK_TIME_B        = config['CURRENT_SETTINGS'].getint('break_time_B', fallback=5)
POMO_ROLE_B         = config['CURRENT_SETTINGS'].get('pomodoro_role_B', fallback='25-5')
POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
PREFIX              = config['CURRENT_SETTINGS'].get('prefix', '*')
MAINTENANCE_MODE    = False

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=PREFIX,
    help_command=None,
    intents=intents,
    case_insensitive=True
)

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# ─── ÉTAT EN MÉMOIRE ────────────────────────────────────────────────────────────
PARTICIPANTS_A = set()
PARTICIPANTS_B = set()

# ─── EXCEPTIONS ────────────────────────────────────────────────────────────────
class SetupIncomplete(commands.CommandError): pass
class WrongChannel(commands.CommandError): pass

# ─── DÉCORATEURS UTILS ─────────────────────────────────────────────────────────
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def check_maintenance():
    async def predicate(ctx):
        if MAINTENANCE_MODE and ctx.command.name != 'maintenance':
            raise commands.CommandError("Bot en mode maintenance.")
        return True
    return commands.check(predicate)

def check_setup():
    async def predicate(ctx):
        guild = ctx.guild
        channel_ok = POMODORO_CHANNEL_ID and bot.get_channel(POMODORO_CHANNEL_ID)
        roleA_ok = discord.utils.get(guild.roles, name=POMO_ROLE_A)
        roleB_ok = discord.utils.get(guild.roles, name=POMO_ROLE_B)
        if channel_ok and roleA_ok and roleB_ok:
            return True
        raise SetupIncomplete()
    return commands.check(predicate)

def check_channel():
    async def predicate(ctx):
        # admin, help, status, update, me → utilisables partout
        if ctx.author.guild_permissions.administrator or ctx.command.name in ('status','help','update','me'):
            return True
        if ctx.channel.id == POMODORO_CHANNEL_ID:
            return True
        raise WrongChannel()
    return commands.check(predicate)

async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name, colour=discord.Colour(0x206694))
        logger.info(f"Rôle '{name}' créé dans '{guild.name}'")
    return role

def get_phase_and_remaining(now: datetime, mode: str) -> tuple[str,int]:
    """Retourne la phase (travail/pause) et le temps restant en secondes."""
    m, sec = now.minute, now.second
    if mode == 'A':
        if m < 50:
            return 'travail', (50-m)*60 - sec
        return 'pause', (60-m)*60 - sec
    if mode == 'B':
        if m < 25:
            return 'travail', (25-m)*60 - sec
        if m < 30:
            return 'pause', (30-m)*60 - sec
        if m < 55:
            return 'travail', (55-m)*60 - sec
        return 'pause', (60-m)*60 - sec
    return 'travail', 0

# ─── ÉVÉNEMENTS ────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    logger.info(f"{bot.user} connecté.")
    await init_db()
    for guild in bot.guilds:
        for uid, mode in await get_all_participants(guild.id):
            (PARTICIPANTS_A if mode=='A' else PARTICIPANTS_B).add(uid)
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, SetupIncomplete):
        return await ctx.send(messages.TEXT["setup_incomplete"])
    if isinstance(error, WrongChannel):
        ch = bot.get_channel(POMODORO_CHANNEL_ID)
        return await ctx.send(f"❌ Utilisez {ch.mention}.")
    key = (
        "command_not_found"   if isinstance(error, commands.CommandNotFound) else
        "maintenance_active"  if isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance." else
        "missing_argument"    if isinstance(error, commands.MissingRequiredArgument) else
        "permission_denied"   if isinstance(error, commands.CheckFailure) else
        "unexpected_error"
    )
    text = messages.TEXT.get(key, messages.TEXT["unexpected_error"]).format(
        prefix=PREFIX, error=str(error)
    )
    await ctx.send(text)

# ─── COMMANDES ÉTUDIANT ────────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre le mode A (50-10)')
@check_maintenance() @check_setup() @check_channel()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(f"🚫 {user.mention}, déjà inscrit.")
    PARTICIPANTS_A.add(user.id)
    await add_participant(user.id, ctx.guild.id, 'A')
    await user.add_roles(await ensure_role(ctx.guild, POMO_ROLE_A))
    ph, rem = get_phase_and_remaining(datetime.now(timezone.utc), 'A')
    m, s = divmod(rem, 60)
    await ctx.send(f"✅ {user.mention} a rejoint A → **{ph}**, reste {m} min {s} s")

@bot.command(name='joinB', help='Rejoindre le mode B (25-5)')
@check_maintenance() @check_setup() @check_channel()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(f"🚫 {user.mention}, déjà inscrit.")
    PARTICIPANTS_B.add(user.id)
    await add_participant(user.id, ctx.guild.id, 'B')
    await user.add_roles(await ensure_role(ctx.guild, POMO_ROLE_B))
    ph, rem = get_phase_and_remaining(datetime.now(timezone.utc), 'B')
    m, s = divmod(rem, 60)
    await ctx.send(f"✅ {user.mention} a rejoint B → **{ph}**, reste {m} min {s} s")

@bot.command(name='leave', help='Quitter la session Pomodoro')
@check_maintenance() @check_setup() @check_channel()
async def leave(ctx):
    """Quand un utilisateur quitte : enregistrer temps + mettre à jour streak."""
    user = ctx.author
    join_ts, mode = await remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(f"🚫 {user.mention}, pas inscrit.")
    elapsed = int(datetime.now(timezone.utc).timestamp() - join_ts)

    if mode == 'A': PARTICIPANTS_A.discard(user.id)
    else:           PARTICIPANTS_B.discard(user.id)

    role_name = POMO_ROLE_A if mode=='A' else POMO_ROLE_B
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role: await user.remove_roles(role)

    await ajouter_temps(user.id, ctx.guild.id, elapsed, mode=mode, is_session_end=True)
    await update_streak(ctx.guild.id, user.id)  # 🔥 mise à jour streak

    m, s = divmod(elapsed, 60)
    await ctx.send(f"👋 {user.mention} a quitté. +{m} min {s} s ajoutées.")

@bot.command(name='me', help='Afficher vos stats personnelles')
@check_maintenance() @check_setup() @check_channel()
async def me(ctx):
    """Affiche stats perso + streaks."""
    user, guild_id = ctx.author, ctx.guild.id

    # Session en cours
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT join_ts, mode FROM participants WHERE guild_id=? AND user_id=?", (guild_id, user.id))
        rec = await cur.fetchone()
    if rec:
        join_ts, mode = rec
        elapsed = int(datetime.now(timezone.utc).timestamp() - join_ts)
        ph, _ = get_phase_and_remaining(datetime.now(timezone.utc), mode)
        status = f"En mode **{mode}** ({ph}) depuis {elapsed//60} min {elapsed%60} s"
    else:
        status = "Pas en session actuellement"

    # Stats globales
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT total_seconds, work_seconds_A, break_seconds_A, work_seconds_B, break_seconds_B, session_count "
            "FROM stats WHERE guild_id=? AND user_id=?", (guild_id, user.id)
        )
        row = await cur.fetchone()
    if row: total_s, wA, bA, wB, bB, scount = row
    else:   total_s = wA = bA = wB = bB = scount = 0

    # Streaks
    current_streak, best_streak = await get_streak(guild_id, user.id)

    # Embed
    embed = discord.Embed(title=f"📋 Stats de {user.name}", color=messages.MsgColors.AQUA.value)
    embed.add_field(name="Session en cours", value=status, inline=False)
    embed.add_field(name="Temps total", value=f"{total_s//60} min", inline=True)
    embed.add_field(name="Mode A travail / pause", value=f"{wA//60} min / {bA//60} min", inline=True)
    embed.add_field(name="Mode B travail / pause", value=f"{wB//60} min / {bB//60} min", inline=True)
    embed.add_field(name="Nombre de sessions", value=str(scount), inline=True)
    avg = (total_s / scount) if scount else 0
    embed.add_field(name="Moyenne/session", value=f"{int(avg)//60} min", inline=True)
    embed.add_field(name="🔥 Streak actuel", value=f"{current_streak} jours", inline=True)
    embed.add_field(name="🌟 Meilleur streak", value=f"{best_streak} jours", inline=True)

    await ctx.send(embed=embed)

@bot.command(name='leaderboard', help='Classements Pomodoro')
@check_maintenance() @check_setup() @check_channel()
async def leaderboard(ctx, category: str = "overall"):
    """Top contributeurs (global, A, B, sessions, moyenne, streaks)."""
    guild_id, cat = ctx.guild.id, category.lower()
    title_map = {
        "overall": ("🏆 Top global", None),
        "A": ("🥇 Top Mode A", "A"),
        "B": ("🥈 Top Mode B", "B"),
        "sessions": ("🔄 Top sessions", "sessions"),
        "avg": ("📊 Top moyenne/session", "avg"),
        "streaks": ("🔥 Top streaks", "streaks"),
    }
    if cat not in title_map:
        return await ctx.send(f"⚠️ Catégorie invalide. Choisissez parmi {', '.join(title_map)}.")

    title, key = title_map[cat]
    e = discord.Embed(title=title, color=messages.LEADERBOARD["color"])

    if cat == "streaks":
        rows = await top_streaks(guild_id, limit=5)
        for i, (uid, curr, best) in enumerate(rows, start=1):
            user = await bot.fetch_user(uid)
            e.add_field(name=f"{i}. {user.name}", value=f"{curr} jours (best {best})", inline=False)
    else:
        rows = await get_all_stats(guild_id)
        entries = []
        for (uid, _, total, wA, bA, wB, bB, sc) in rows:
            if cat=="overall": score,label=total,f"{total/60:.1f} min"
            elif cat=="A":     score,label=wA,f"{wA/60:.1f} / {bA/60:.1f} min"
            elif cat=="B":     score,label=wB,f"{wB/60:.1f} / {bB/60:.1f} min"
            elif cat=="sessions": score,label=sc,f"{sc} sessions"
            else: score=(total/sc) if sc else 0; m,s=divmod(int(score),60); label=f"{m} min {s} s"
            entries.append((uid, score, label))
        entries.sort(key=lambda x: x[1], reverse=True)
        for i,(uid,_,label) in enumerate(entries[:5], start=1):
            user = await bot.fetch_user(uid)
            e.add_field(name=f"{i}. {user.name}", value=label, inline=False)

    await ctx.send(embed=e)

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def pomodoro_loop():
    """Boucle d’enregistrement automatique A/B + streak update."""
    now, minute = datetime.now(timezone.utc), datetime.now(timezone.utc).minute
    chan = bot.get_channel(POMODORO_CHANNEL_ID)
    if not chan: return

    # MODE A
    if PARTICIPANTS_A:
        mention = (await ensure_role(chan.guild, POMO_ROLE_A)).mention
        if minute == WORK_TIME_A:
            for uid in PARTICIPANTS_A:
                await ajouter_temps(uid, chan.guild.id, WORK_TIME_A*60, mode='A', is_session_end=True)
                await update_streak(chan.guild.id, uid)  # 🔥 streak
            await chan.send(f"☕ Mode A : pause ({BREAK_TIME_A} min) {mention}")

    # MODE B
    if PARTICIPANTS_B:
        mention = (await ensure_role(chan.guild, POMO_ROLE_B)).mention
        if minute == WORK_TIME_B:
            for uid in PARTICIPANTS_B:
                await ajouter_temps(uid, chan.guild.id, WORK_TIME_B*60, mode='B', is_session_end=True)
                await update_streak(chan.guild.id, uid)  # 🔥 streak
            await chan.send(f"☕ Mode B : pause 1 ({BREAK_TIME_B} min) {mention}")
        elif minute == 2*WORK_TIME_B + BREAK_TIME_B:
            for uid in PARTICIPANTS_B:
                await ajouter_temps(uid, chan.guild.id, WORK_TIME_B*60, mode='B', is_session_end=True)
                await update_streak(chan.guild.id, uid)  # 🔥 streak
            await chan.send(f"☕ Mode B : pause finale ({BREAK_TIME_B} min) {mention}")

# ─── LANCEMENT ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    bot.run(TOKEN)
