import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
from enum import Enum
from database import add_participant, remove_participant, get_all_participants, classement_top10
from keep_alive import keep_alive
import logging
from tinydb import TinyDB
from datetime import datetime, timezone, timedelta

# CONFIG & GLOBALS
config = configparser.ConfigParser()
config.read('settings.ini')

prefix = config['CURRENT_SETTINGS'].get('prefix', '*')
BOT_TOKEN = os.getenv('DISCORD_TOKEN')
WORK_A = int(config['CURRENT_SETTINGS'].get('work_time', 50))
BREAK_A = int(config['CURRENT_SETTINGS'].get('break_time', 10))
WORK_B = int(config['CURRENT_SETTINGS'].get('work_time_b', 25))
BREAK_B = int(config['CURRENT_SETTINGS'].get('break_time_b', 5))
CHAN_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
ROLE_A = config['CURRENT_SETTINGS'].get('pomodoro_role', '50-10')
ROLE_B = config['CURRENT_SETTINGS'].get('pomodoro_role_b', '25-5')

SESSION_ACTIVE = False
SESSION_PHASE = None  # 'work' or 'break'
SESSION_END = None
# participants: dict user_id->mode 'A' or 'B'
PARTICIPANTS = {}

# BOT setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(prefix, help_command=None, intents=intents, case_insensitive=True)

# Logging
logger = logging.getLogger('pomobot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# Colors
class MsgColors(Enum):
    AQUA = 0x33c6bb
    PURPLE = 0x6040b1
    RED = 0xEA3546

# Checks
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def check_maintenance_mode():
    async def predicate(ctx):
        return True
    return commands.check(predicate)

# Utils
def get_or_create_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = guild.create_role(name=name)
    return role

# EVENTS
@bot.event
async def on_ready():
    logger.info(f"{bot.user} ready.")
    # ask config if missing
    for guild in bot.guilds:
        # channel
        if not CHAN_ID or not bot.get_channel(CHAN_ID):
            try:
                await guild.owner.send(
                    f"Veuillez configurer le salon Pomodoro avec `{prefix}set_channel #salon`."
                )
            except:
                pass
        # roles
        for role_name in (ROLE_A, ROLE_B):
            if not discord.utils.get(guild.roles, name=role_name):
                try:
                    await guild.owner.send(
                        f"Veuillez configurer/créer le rôle Pomodoro '{role_name}' ou laissez le bot le créer automatiquement."
                    )
                except:
                    pass
    # reload participants
    if CHAN_ID:
        chan = bot.get_channel(CHAN_ID)
        if chan:
            PARTICIPANTS.clear()
            PARTICIPANTS.update({uid:mode for uid,mode in [ (u, 'A') for u in get_all_participants(chan.guild.id) ]})
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"Commande inconnue. Tapez `{prefix}help`.")
    else:
        await ctx.send(f"Erreur : {error}")
        logger.error(error)

# COMMANDS
@bot.command(name='set_channel')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini','w') as f: config.write(f)
    global CHAN_ID
    CHAN_ID = channel.id
    await ctx.send(f"Canal défini sur {channel.mention}")

@bot.command(name='set_role')
@is_admin()
async def set_role(ctx, role: discord.Role, mode: str):
    mode = mode.upper()
    if mode == 'A':
        config['CURRENT_SETTINGS']['pomodoro_role'] = role.name
    elif mode == 'B':
        config['CURRENT_SETTINGS']['pomodoro_role_b'] = role.name
    else:
        return await ctx.send("Mode invalide, utilisez A ou B.")
    with open('settings.ini','w') as f: config.write(f)
    await ctx.send(f"Rôle mode {mode} défini sur {role.name}")

@bot.command(name='joina')
@check_maintenance_mode()
async def joina(ctx):
    uid, gid = ctx.author.id, ctx.guild.id
    PARTICIPANTS[uid] = 'A'
    add_participant(uid, gid)
    role = get_or_create_role(ctx.guild, ROLE_A)
    await ctx.author.add_roles(role)
    await ctx.send(f"{ctx.author.mention} a rejoint mode A (50-10)")

@bot.command(name='joinb')
@check_maintenance_mode()
async def joinb(ctx):
    uid, gid = ctx.author.id, ctx.guild.id
    PARTICIPANTS[uid] = 'B'
    add_participant(uid, gid)
    role = get_or_create_role(ctx.guild, ROLE_B)
    await ctx.author.add_roles(role)
    await ctx.send(f"{ctx.author.mention} a rejoint mode B (25-5)")

@bot.command(name='leave')
@check_maintenance_mode()
async def leave(ctx):
    uid, gid = ctx.author.id, ctx.guild.id
    if uid in PARTICIPANTS:
        PARTICIPANTS.pop(uid)
        join_ts = remove_participant(uid, gid)
        if join_ts:
            elapsed = int((datetime.now(timezone.utc).timestamp()-join_ts)/60)
            ajouter_temps(uid, gid, elapsed)
        await ctx.author.remove_roles(
            discord.utils.get(ctx.guild.roles, name=ROLE_A) or discord.utils.get(ctx.guild.roles, name=ROLE_B)
        )
        await ctx.send(f"{ctx.author.mention} a quitté, +{elapsed if join_ts else 0} min.")
    else:
        await ctx.send(f"{ctx.author.mention} n'était pas inscrit.")

@bot.command(name='time')
@check_maintenance_mode()
async def time_left(ctx):
    if not SESSION_ACTIVE:
        return await ctx.send("Aucune session en cours.")
    rem = SESSION_END - datetime.now(timezone.utc)
    m,s = divmod(max(int(rem.total_seconds()),0),60)
    phase = 'travail' if SESSION_PHASE=='work' else 'pause'
    await ctx.send(f"Session {phase}: {m} min {s} sec restants.")

@bot.command(name='stats')
@check_maintenance_mode()
async def stats(ctx):
    table = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    users = table.all(); total = sum(u['minutes'] for u in users);
    count = len(users)
    await ctx.send(f"Utilisateurs: {count}, Total: {total} min")

@bot.command(name='leaderboard')
async def leaderboard(ctx):
    top = classement_top10(ctx.guild.id)
    if not top:
        return await ctx.send("Aucun utilisateur.")
    msg = '\n'.join(f"#{i+1} <@{uid}> : {mins} min" for i,(uid,mins) in enumerate(top,1))
    await ctx.send(msg)

@bot.command(name='help')
async def help_cmd(ctx):
    cmds = [
        ('Étudiant', ['joina','joinb','leave','time','stats','help']),
        ('Admin', ['set_channel #salon','set_role @rôle A|B','leaderboard','clear_stats'])
    ]
    lines = []
    for cat, lst in cmds:
        lines.append(f"**{cat}**: {', '.join(lst)}")
    await ctx.send("\n".join(lines))

@bot.command(name='clear_stats')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').purge()
    await ctx.send("Stats purgées.")

# POMODORO LOOP
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    if not PARTICIPANTS: return
    cfg = { 'A':(WORK_A,BREAK_A), 'B':(WORK_B,BREAK_B) }
    # for each mode separately? simplified: one global session uses mixed modes
    # implement separate loops later
    # here assume single global session A
    work, brk = WORK_A, BREAK_A
    SESSION_ACTIVE, SESSION_PHASE = True, 'work'
    SESSION_END = datetime.now(timezone.utc)+timedelta(minutes=work)
    chan = bot.get_channel(CHAN_ID)
    if chan: await chan.send(f"Début travail ({work} min)")
    await asyncio.sleep(work*60)
    SESSION_PHASE = 'break'
    SESSION_END = datetime.now(timezone.utc)+timedelta(minutes=brk)
    if chan: await chan.send(f"Début pause ({brk} min)")
    await asyncio.sleep(brk*60)
    for uid in list(PARTICIPANTS): ajouter_temps(uid, chan.guild.id, work)
    SESSION_ACTIVE = False

if __name__ == '__main__':
    keep_alive()
    bot.run(BOT_TOKEN)
