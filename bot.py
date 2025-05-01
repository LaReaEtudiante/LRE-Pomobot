import os
import discord
from discord.ext import commands
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
POMO_ROLE_A  = config['CURRENT_SETTINGS'].get('pomodoro_role_A',   fallback='50-10')
WORK_TIME_B  = config['CURRENT_SETTINGS'].getint('work_time_B', fallback=25)
BREAK_TIME_B = config['CURRENT_SETTINGS'].getint('break_time_B', fallback=5)
POMO_ROLE_B  = config['CURRENT_SETTINGS'].get('pomodoro_role_B',   fallback='25-5')

POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
PREFIX = config['CURRENT_SETTINGS'].get('prefix', '*')
MAINTENANCE_MODE = False

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

# ─── STATE ─────────────────────────────────────────────────────────────────────
SESSION_ACTIVE = True  # always active based on clock

PARTICIPANTS_A = set()
PARTICIPANTS_B = set()

# ─── UTILS ─────────────────────────────────────────────────────────────────────
def is_admin():
    async def predicate(ctx): return ctx.author.guild_permissions.administrator
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


def compute_phase_remaining(mode: str) -> (str, int, int):
    now = datetime.now(timezone.utc)
    tot = now.minute*60 + now.second
    if mode == 'A':
        work = WORK_TIME_A*60
        cycle = 3600
        if tot < work:
            phase = 'work'
            rem = work - tot
        else:
            phase = 'pause'
            rem = cycle - tot
    else:
        # B segments: 0-25,25-30,30-55,55-60
        if tot < 25*60:
            phase = 'work'; rem = 25*60 - tot
        elif tot < 30*60:
            phase = 'pause'; rem = 30*60 - tot
        elif tot < 55*60:
            phase = 'work'; rem = 55*60 - tot
        else:
            phase = 'pause'; rem = 3600 - tot
    return phase, rem//60, rem%60

# ─── EVENTS ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global MAINTENANCE_MODE
    logger.info(f"{bot.user} connecté.")
    # restore participants
    for guild in bot.guilds:
        for uid, mode in get_all_participants(guild.id):
            if mode == 'A': PARTICIPANTS_A.add(uid)
            else: PARTICIPANTS_B.add(uid)
    # launch loops
    bot.loop.create_task(mode_loop('A'))
    bot.loop.create_task(mode_loop('B'))

@bot.event
async def on_command_error(ctx, error):
    key = ('command_not_found' if isinstance(error, commands.CommandNotFound)
           else 'maintenance_active' if isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance."
           else 'missing_argument' if isinstance(error, commands.MissingRequiredArgument)
           else 'permission_denied' if isinstance(error, commands.CheckFailure)
           else 'unexpected_error')
    err = messages.ERRORS[key]
    desc = err.get('description_template', '').format(prefix=PREFIX, error=str(error))
    e = discord.Embed(title=err.get('title',''), description=desc, color=err['color'])
    await ctx.send(embed=e)

# ─── JOIN / LEAVE ─────────────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(f"🚫 Vous êtes déjà inscrit.")
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    phase, m, s = compute_phase_remaining('A')
    await ctx.send(f"✅ {user.mention} a rejoint (mode A – 50-10). Session **{ 'travail' if phase=='work' else 'pause' }** en cours, prochaine transition dans **{m}** min **{s}** sec.")

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(f"🚫 Vous êtes déjà inscrit.")
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id, 'B')
    role = await ensure_role(ctx.guild, POMO_ROLE_B)
    await user.add_roles(role)
    phase, m, s = compute_phase_remaining('B')
    await ctx.send(f"✅ {user.mention} a rejoint (mode B – 25-5). Session **{ 'travail' if phase=='work' else 'pause' }** en cours, prochaine transition dans **{m}** min **{s}** sec.")

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(f"🚫 {user.mention} n'était pas inscrit.")
    now_ts = datetime.now(timezone.utc).timestamp()
    mins = max(int((now_ts-join_ts)//60), 1)
    ajouter_temps(user.id, ctx.guild.id, mins)
    if mode=='A':
        PARTICIPANTS_A.discard(user.id)
        role = discord.utils.get(ctx.guild.roles,name=POMO_ROLE_A)
    else:
        PARTICIPANTS_B.discard(user.id)
        role = discord.utils.get(ctx.guild.roles,name=POMO_ROLE_B)
    if role: await user.remove_roles(role)
    await ctx.send(f"✅ {user.mention} a quitté. +{mins} min ajoutées.")

# ─── Helper: mode loop ─────────────────────────────────────────────────────────
async def mode_loop(mode: str):
    participants = PARTICIPANTS_A if mode=='A' else PARTICIPANTS_B
    work = WORK_TIME_A if mode=='A' else WORK_TIME_B
    brk  = BREAK_TIME_A if mode=='A' else BREAK_TIME_B
    role_name = POMO_ROLE_A if mode=='A' else POMO_ROLE_B
    channel = None
    while True:
        now = datetime.now(timezone.utc)
        tot = now.minute*60 + now.second
        # determine current phase
        if mode=='A':
            if tot < work*60:
                phase = 'work'; end_sec = work*60
            else:
                phase = 'break'; end_sec = 3600
        else:
            if tot < 25*60:
                phase='work'; end_sec=25*60
            elif tot < 30*60:
                phase='break'; end_sec=30*60
            elif tot < 55*60:
                phase='work'; end_sec=55*60
            else:
                phase='break'; end_sec=3600
        # next transition absolute
        base = now.replace(minute=0, second=0, microsecond=0)
        next_time = base + timedelta(seconds=end_sec)
        if next_time <= now: next_time += timedelta(hours=1)
        delay = (next_time - now).total_seconds()
        await asyncio.sleep(delay)
        # flip phase
        new_phase = 'break' if phase=='work' else 'work'
        duration = work if new_phase=='work' else brk
        # get channel & mention
        if not channel:
            channel = bot.get_channel(POMODORO_CHANNEL_ID)
        mention = (await ensure_role(channel.guild, role_name)).mention
        if participants:
            await channel.send(f"🔔 Début **{ 'travail' if new_phase=='work' else 'pause' }** (mode {mode}, {duration} min) ! {mention}")
        # record work at transition from work->break
        if phase=='work':
            for uid in list(participants):
                ajouter_temps(uid, channel.guild.id, work)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
