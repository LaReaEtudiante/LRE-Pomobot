import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from tinydb import TinyDB
from database import (
    ajouter_temps,
    classement_top10,
    add_participant,
    remove_participant,
    get_all_participants
)
from keep_alive import keep_alive
import messages

# ─── CONFIG & GLOBALS ─────────────────────────────────────────────────────────
config = configparser.ConfigParser()
config.read('settings.ini')

WORK_TIME_A  = config['CURRENT_SETTINGS'].getint('work_time_A', fallback=50)
BREAK_TIME_A = config['CURRENT_SETTINGS'].getint('break_time_A', fallback=10)
POMO_ROLE_A  = config['CURRENT_SETTINGS'].get('pomodoro_role_A', fallback='50-10')
WORK_TIME_B  = config['CURRENT_SETTINGS'].getint('work_time_B', fallback=25)
BREAK_TIME_B = config['CURRENT_SETTINGS'].getint('break_time_B', fallback=5)
POMO_ROLE_B  = config['CURRENT_SETTINGS'].get('pomodoro_role_B', fallback='25-5')

POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
PREFIX = config['CURRENT_SETTINGS'].get('prefix', '*')
MAINTENANCE_MODE = False

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, help_command=None, intents=intents, case_insensitive=True)

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# ─── STATE ─────────────────────────────────────────────────────────────────────
SESSION_END_A     = None
SESSION_PHASE_A   = None
SESSION_END_B     = None
SESSION_PHASE_B   = None
PARTICIPANTS_A    = set()
PARTICIPANTS_B    = set()

# ─── UTILS ─────────────────────────────────────────────────────────────────────
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

async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name)
        logger.info(f"Rôle '{name}' créé dans '{guild.name}'")
    return role

# ─── EVENTS ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global MAINTENANCE_MODE
    logger.info(f"{bot.user} connecté.")
    # restaurer participants
    for guild in bot.guilds:
        for uid, mode in get_all_participants(guild.id):
            if mode == 'A':
                PARTICIPANTS_A.add(uid)
            else:
                PARTICIPANTS_B.add(uid)
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    key = (
        "command_not_found" if isinstance(error, commands.CommandNotFound)
        else "maintenance_active" if isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance."
        else "missing_argument" if isinstance(error, commands.MissingRequiredArgument)
        else "permission_denied" if isinstance(error, commands.CheckFailure)
        else "unexpected_error"
    )
    err = messages.ERRORS[key]
    e = discord.Embed(
        title=err.get("title",""),
        description=err.get("description_template","").format(prefix=PREFIX, error=str(error)),
        color=err["color"]
    )
    await ctx.send(embed=e)

# ─── COMMANDES ÉTUDIANT ────────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit.",
            color=messages.MsgColors.YELLOW.value
        ))
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    tpl = messages.JOIN["A"]
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(user_mention=user.mention),
        color=tpl["color"]
    ))

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit.",
            color=messages.MsgColors.YELLOW.value
        ))
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id, 'B')
    role = await ensure_role(ctx.guild, POMO_ROLE_B)
    await user.add_roles(role)
    tpl = messages.JOIN["B"]
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(user_mention=user.mention),
        color=tpl["color"]
    ))

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(embed=discord.Embed(
            description=f"{user.mention} n'était pas inscrit.",
            color=messages.MsgColors.YELLOW.value
        ))
    now_ts = datetime.now(timezone.utc).timestamp()
    mins = max(int((now_ts-join_ts)//60), 1)
    ajouter_temps(user.id, ctx.guild.id, mins)
    if mode=='A':
        PARTICIPANTS_A.discard(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_A)
    else:
        PARTICIPANTS_B.discard(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_B)
    if role: await user.remove_roles(role)
    tpl = messages.LEAVE
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(user_mention=user.mention, minutes=mins),
        color=tpl["color"]
    ))

# ─── COMMANDE *time ───────────────────────────────────────────────────────────
@bot.command(name='time', help='Temps restant sessions A & B')
@check_maintenance()
async def time_left(ctx):
    tpl = messages.TIME_LEFT
    e = discord.Embed(title=tpl["title"], color=tpl["color"])
    # mode A
    if SESSION_END_A:
        remA = max(int((SESSION_END_A - datetime.now(timezone.utc)).total_seconds()),0)
        mA, sA = divmod(remA,60)
        e.add_field(name="Mode A", value=f"{SESSION_PHASE_A} dans {mA}m {sA}s", inline=False)
    else:
        e.add_field(name="Mode A", value="pas de session", inline=False)
    # mode B
    if SESSION_END_B:
        remB = max(int((SESSION_END_B - datetime.now(timezone.utc)).total_seconds()),0)
        mB, sB = divmod(remB,60)
        e.add_field(name="Mode B", value=f"{SESSION_PHASE_B} dans {mB}m {sB}s", inline=False)
    else:
        e.add_field(name="Mode B", value="pas de session", inline=False)
    await ctx.send(embed=e)

# ─── COMMANDE STATUS ─────────────────────────────────────────────────────────
@bot.command(name='status', help='Afficher état détaillé du bot')
async def status(ctx):
    latency = round(bot.latency*1000)
    local = datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Zurich'))
    maint = "activée" if MAINTENANCE_MODE else "désactivée"
    sess = "aucune session"
    if SESSION_END_A or SESSION_END_B:
        # on affiche celle en cours
        current = "A" if SESSION_END_A and (not SESSION_END_B or SESSION_END_A>SESSION_END_B) else "B"
        end = SESSION_END_A if current=="A" else SESSION_END_B
        phase = SESSION_PHASE_A if current=="A" else SESSION_PHASE_B
        rem = max(int((end - datetime.now(timezone.utc)).total_seconds()),0)
        m, s = divmod(rem,60)
        sess = f"mode {current} ({phase}) dans {m}m{s}s"
    e = discord.Embed(title=messages.STATUS["title"], color=messages.STATUS["color"])
    for f in messages.STATUS["fields"]:
        val = f["value_template"].format(
            latency=latency,
            local_time=local.strftime("%Y-%m-%d %H:%M:%S"),
            maintenance=maint,
            count_A=len(PARTICIPANTS_A),
            count_B=len(PARTICIPANTS_B),
            session_status=sess
        )
        e.add_field(name=f["name"], value=val, inline=f["inline"])
    await ctx.send(embed=e)

# ─── STATS & LEADERBOARD ───────────────────────────────────────────────────────
@bot.command(name='stats', help='Vos stats détaillées')
@check_maintenance()
async def stats(ctx):
    db = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    all_ = db.all()
    total_A = sum(u['minutes'] for u in all_ if u.get('mode','')=='A')
    total_B = sum(u['minutes'] for u in all_ if u.get('mode','')=='B')
    unique = len(all_)
    total  = sum(u['minutes'] for u in all_)
    avg    = (total/unique) if unique else 0
    e = discord.Embed(title=messages.STATS["title"], color=messages.STATS["color"])
    for f in messages.STATS["fields"]:
        val = f["value_template"].format(
            unique_users=unique,
            total_minutes=total,
            average_minutes=avg,
            total_A=total_A,
            total_B=total_B
        )
        e.add_field(name=f["name"], value=val, inline=f["inline"])
    await ctx.send(embed=e)

# ─── LEADERBOARD ──────────────────────────────────────────────────────────────
@bot.command(name='leaderboard', help='Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top5 = classement_top10(ctx.guild.id)[:5]
    e = discord.Embed(title=messages.LEADERBOARD["title"], color=messages.LEADERBOARD["color"])
    if not top5:
        e.description = "Aucun utilisateur."
    else:
        for i,(uid,mins) in enumerate(top5,1):
            user = await ctx.fetch_user(uid)
            e.add_field(
                name=messages.LEADERBOARD["entry_template"]["name_template"].format(rank=i,username=user.name),
                value=messages.LEADERBOARD["entry_template"]["value_template"].format(minutes=mins),
                inline=False
            )
    await ctx.send(embed=e)

# ─── ADMIN ─────────────────────────────────────────────────────────────────────
@bot.command(name='maintenance', help='Mode maintenance on/off')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    tpl = messages.MAINT_TOGGLE
    await ctx.send(embed=discord.Embed(
        title=tpl["title"],
        description=tpl["description_template"].format(state=state),
        color=tpl["color"]
    ))

# ... (set_channel, set_role_A, set_role_B, clear_stats, help restent inchangés)

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_END_A, SESSION_PHASE_A, SESSION_END_B, SESSION_PHASE_B
    cid = POMODORO_CHANNEL_ID
    channel = bot.get_channel(cid) if cid else None
    if not channel or not (PARTICIPANTS_A|PARTICIPANTS_B):
        return

    for mode, participants, work, pause, role_name in (
        ('A', PARTICIPANTS_A, WORK_TIME_A, BREAK_TIME_A, POMO_ROLE_A),
        ('B', PARTICIPANTS_B, WORK_TIME_B, BREAK_TIME_B, POMO_ROLE_B)
    ):
        if not participants: continue
        # travail
        if mode=='A':
            SESSION_PHASE_A = 'travail'; SESSION_END_A = datetime.now(timezone.utc)+timedelta(minutes=work)
        else:
            SESSION_PHASE_B = 'travail'; SESSION_END_B = datetime.now(timezone.utc)+timedelta(minutes=work)
        mention = (await ensure_role(channel.guild, role_name)).mention
        await channel.send(messages.LOOP["start_template"].format(mode=mode, duration=work, role_mention=mention))
        await asyncio.sleep(work*60)
        # pause
        if mode=='A':
            SESSION_PHASE_A = 'pause'; SESSION_END_A = datetime.now(timezone.utc)+timedelta(minutes=pause)
        else:
            SESSION_PHASE_B = 'pause'; SESSION_END_B = datetime.now(timezone.utc)+timedelta(minutes=pause)
        await channel.send(messages.LOOP["pause_template"].format(mode=mode, duration=pause, role_mention=mention))
        await asyncio.sleep(pause*60)
        # enregistrer
        for uid in list(participants):
            ajouter_temps(uid, channel.guild.id, work)
    # fin de tous les modes
    SESSION_END_A = SESSION_END_B = None

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
