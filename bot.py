# bot.py

from dotenv import load_dotenv
import os
import sys
import asyncio
import discord
from discord.ext import commands, tasks
import configparser
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
import messages
from database import (
    DB_PATH,
    init_db,
    ajouter_temps,
    get_all_stats,
    classement_top10,
    add_participant,
    remove_participant,
    get_all_participants,
    get_daily_totals,
    get_weekly_sessions,
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

# ─── EXCEPTIONS PERSONNALISÉES ──────────────────────────────────────────────────
class SetupIncomplete(commands.CommandError):
    pass

class WrongChannel(commands.CommandError):
    pass

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
        # allow admin, help, status, update, me anywhere
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

# ─── ÉVÉNEMENTS ─────────────────────────────────────────────────────────────────
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
@check_maintenance()
@check_setup()
@check_channel()
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
@check_maintenance()
@check_setup()
@check_channel()
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
@check_maintenance()
@check_setup()
@check_channel()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = await remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(f"🚫 {user.mention}, pas inscrit.")
    elapsed = int(datetime.now(timezone.utc).timestamp() - join_ts)
    if mode == 'A':
        PARTICIPANTS_A.discard(user.id)
    else:
        PARTICIPANTS_B.discard(user.id)
    role_name = POMO_ROLE_A if mode=='A' else POMO_ROLE_B
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role:
        await user.remove_roles(role)
    await ajouter_temps(
        user.id,
        ctx.guild.id,
        elapsed,
        mode=mode,
        is_session_end=True
    )
    m, s = divmod(elapsed, 60)
    await ctx.send(f"👋 {user.mention} a quitté. +{m} min {s} s ajoutées.")

@bot.command(name='me', help='Afficher vos stats personnelles')
@check_maintenance()
@check_setup()
@check_channel()
async def me(ctx):
    user = ctx.author
    guild_id = ctx.guild.id

    # 1) Lire la session en cours (sans la supprimer)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT join_ts, mode FROM participants WHERE guild_id=? AND user_id=?",
            (guild_id, user.id)
        )
        rec = await cur.fetchone()

    if rec:
        join_ts, mode = rec
        elapsed = int(datetime.now(timezone.utc).timestamp() - join_ts)
        ph, _ = get_phase_and_remaining(datetime.now(timezone.utc), mode)
        status = f"En mode **{mode}** ({ph}) depuis {elapsed//60} min {elapsed%60} s"
    else:
        status = "Pas en session actuellement"

    # 2) Récup stats
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT total_seconds, work_seconds_A, break_seconds_A, work_seconds_B, break_seconds_B, session_count "
            "FROM stats WHERE guild_id=? AND user_id=?",
            (guild_id, user.id)
        )
        row = await cur.fetchone()
    if row:
        total_s, wA, bA, wB, bB, scount = row
    else:
        total_s = wA = bA = wB = bB = scount = 0

    # 3) Streaks
    cs, bs = await get_streak(guild_id, user.id)

    # 4) Embed
    embed = discord.Embed(
        title=f"📋 Stats de {user.name}",
        color=messages.MsgColors.AQUA.value
    )
    embed.add_field(name="Session en cours", value=status, inline=False)
    embed.add_field(name="Temps total", value=f"{total_s//60} min {total_s%60} s", inline=False)
    embed.add_field(name="Mode A travail / pause", value=f"{wA//60} / {bA//60} min", inline=True)
    embed.add_field(name="Mode B travail / pause", value=f"{wB//60} / {bB//60} min", inline=True)
    embed.add_field(name="Nombre de sessions", value=str(scount), inline=True)
    avg = (total_s / scount) if scount else 0
    embed.add_field(name="Moyenne/session", value=f"{int(avg)//60} min {int(avg)%60} s", inline=True)
    embed.add_field(name="🔥 Streak actuel", value=f"{cs} jours", inline=True)
    embed.add_field(name="🏅 Meilleur streak", value=f"{bs} jours", inline=True)

    await ctx.send(embed=embed)

@bot.command(name='status', help='Afficher état global du bot')
async def status(ctx):
    latency = round(bot.latency * 1000)
    now_utc = datetime.now(timezone.utc)
    try:
        local = now_utc.astimezone(ZoneInfo('Europe/Zurich'))
    except ZoneInfoNotFoundError:
        local = now_utc.astimezone()
    local_str = local.strftime("%Y-%m-%d %H:%M:%S")
    phA, rA = get_phase_and_remaining(now_utc, 'A')
    phB, rB = get_phase_and_remaining(now_utc, 'B')
    mA, sA = divmod(rA, 60)
    mB, sB = divmod(rB, 60)
    countA = len(PARTICIPANTS_A)
    countB = len(PARTICIPANTS_B)
    chan = bot.get_channel(POMODORO_CHANNEL_ID)
    chan_field  = f"✅ {chan.mention}" if chan else "❌ non configuré"
    guild       = ctx.guild
    roleA       = discord.utils.get(guild.roles, name=POMO_ROLE_A)
    roleB       = discord.utils.get(guild.roles, name=POMO_ROLE_B)
    roleA_field = f"✅ {roleA.mention}" if roleA else "❌ non configuré"
    roleB_field = f"✅ {roleB.mention}" if roleB else "❌ non configuré"
    proc = await asyncio.create_subprocess_shell(
        "git rev-parse --short HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    sha = out.decode().strip() if out else "unknown"
    try:
        with open("VERSION", encoding="utf-8") as f:
            file_ver = f.read().strip()
    except FileNotFoundError:
        file_ver = "unknown"

    e = discord.Embed(title=messages.STATUS["title"], color=messages.STATUS["color"])
    e.add_field(name="Latence", value=f"{latency} ms", inline=True)
    e.add_field(name="Heure (Lausanne)", value=local_str, inline=True)
    e.add_field(name="Mode A", value=f"{countA} en **{phA}** pour {mA}m {sA}s", inline=False)
    e.add_field(name="Mode B", value=f"{countB} en **{phB}** pour {mB}m {sB}s", inline=False)
    e.add_field(name="Canal Pomodoro", value=chan_field, inline=False)
    e.add_field(name="Rôle A", value=roleA_field, inline=False)
    e.add_field(name="Rôle B", value=roleB_field, inline=False)
    e.add_field(name="Version (SHA)", value=sha, inline=True)
    e.add_field(name="Version (fichier)", value=file_ver, inline=True)
    await ctx.send(embed=e)

@bot.command(name='stats', help='Afficher stats du serveur')
@check_maintenance()
@check_setup()
@check_channel()
async def stats(ctx):
    guild_id = ctx.guild.id
    data    = await get_all_stats(guild_id)
    unique  = len(data)
    total_s = sum(r[2] for r in data)
    avg     = (total_s/unique) if unique else 0
    daily = await get_daily_totals(guild_id, days=7)
    daily_str = "\n".join(f"{day}: {secs//60} m" for day, secs in daily) or "aucune donnée"
    weekly = await get_weekly_sessions(guild_id, weeks=4)
    weekly_str = "\n".join(f"{yw}: {count}" for yw, count in weekly) or "aucune donnée"
    e = discord.Embed(title=messages.STATS["title"], color=messages.STATS["color"])
    e.add_field(name="Utilisateurs uniques", value=str(unique), inline=False)
    e.add_field(name="Temps total (min)", value=f"{total_s/60:.1f}", inline=False)
    e.add_field(name="Moyenne/utilisateur (min)", value=f"{avg/60:.1f}", inline=False)
    e.add_field(name="📅 Totaux 7 jours", value=daily_str, inline=False)
    e.add_field(name="🗓 Sessions / semaine", value=weekly_str, inline=False)
    await ctx.send(embed=e)

@bot.command(name='leaderboard', help='Classements divers')
@check_maintenance()
@check_setup()
@check_channel()
async def leaderboard(ctx):
    guild_id = ctx.guild.id
    rows = await get_all_stats(guild_id)
    entries_overall = [(uid, total) for (uid, _, total, *_ ) in rows]
    entries_A = [(uid, wA) for (uid, _, _, wA, _, _, _, _) in rows]
    entries_B = [(uid, wB) for (uid, _, _, _, _, wB, _, _) in rows]
    entries_avg = [
        (uid, (total/sc) if sc>=10 else 0)
        for (uid, _, total, _, _, _, _, sc) in rows
    ]
    entries_sessions = [(uid, sc) for (uid, _, _, _, _, _, _, sc) in rows]
    def top(entries, n=5):
        return sorted(entries, key=lambda x:x[1], reverse=True)[:n]
    e = discord.Embed(title="🏆 Leaderboard", color=messages.LEADERBOARD["color"])
    for title, entries in [
        ("🌍 Top 10 Global", top(entries_overall, 10)),
        ("🥇 Top 5 Mode A", top(entries_A)),
        ("🥈 Top 5 Mode B", top(entries_B)),
        ("📊 Top 5 Moyenne/session (10+)", top(entries_avg)),
        ("🔄 Top 5 Sessions", top(entries_sessions)),
    ]:
        if not entries or all(val==0 for _,val in entries):
            value="aucune donnée"
        else:
            lines=[]
            for i,(uid,val) in enumerate(entries,start=1):
                user=await bot.fetch_user(uid)
                if isinstance(val,float):
                    m,s=divmod(int(val),60)
                    label=f"{m}m{s}s"
                else:
                    label=str(val)
                lines.append(f"{i}. {user.name} — {label}")
            value="\n".join(lines)
        e.add_field(name=title, value=value, inline=False)
# ─── LANCEMENT ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    bot.run(TOKEN)
