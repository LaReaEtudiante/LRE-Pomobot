import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from tinydb import TinyDB

import messages
from database import (
    ajouter_temps,
    classement_top10,
    add_participant,
    remove_participant,
    get_all_participants,
)
from keep_alive import keep_alive

# ─── CONFIGURATION & GLOBALS ─────────────────────────────────────────────────
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
SESSION_ACTIVE = False
SESSION_PHASE  = None
SESSION_END    = None
PARTICIPANTS_A = set()
PARTICIPANTS_B = set()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=PREFIX,
    help_command=None,
    intents=intents,
    case_insensitive=True
)

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# ─── UTILS ────────────────────────────────────────────────────────────────────
def build_embed(spec: dict, **kwargs) -> discord.Embed:
    """Construit un discord.Embed à partir d’un spec de messages.py"""
    # titre
    if 'title_template' in spec:
        title = spec['title_template'].format(**kwargs)
    else:
        title = spec.get('title', None)
    color = spec.get('color')
    embed = discord.Embed(title=title, color=color)
    # description
    if 'description_template' in spec:
        embed.description = spec['description_template'].format(**kwargs)
    elif 'description' in spec:
        embed.description = spec['description']
    # champs
    for field in spec.get('fields', []):
        name = field['name']
        if 'value_template' in field:
            value = field['value_template'].format(**kwargs)
        else:
            value = field.get('value')
        embed.add_field(name=name, value=value, inline=field.get('inline', False))
    return embed

async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name)
        logger.info(f"Rôle '{name}' créé dans '{guild.name}'")
    return role

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

# ─── ÉVÉNEMENTS ────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global MAINTENANCE_MODE
    logger.info(f"{bot.user} connecté.")
    # charger participants
    for guild in bot.guilds:
        for uid, mode in get_all_participants(guild.id):
            if mode == 'A': PARTICIPANTS_A.add(uid)
            elif mode == 'B': PARTICIPANTS_B.add(uid)
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        spec = messages.ERRORS['command_not_found']
    elif isinstance(error, commands.CommandError) and str(error) == "Bot en mode maintenance.":
        spec = messages.ERRORS['maintenance_active']
    elif isinstance(error, commands.MissingRequiredArgument):
        spec = messages.ERRORS['missing_argument']
    elif isinstance(error, commands.CheckFailure):
        spec = messages.ERRORS['permission_denied']
    else:
        spec = messages.ERRORS['unexpected_error']
        return await ctx.send(embed=build_embed(spec, error=error))
    await ctx.send(embed=build_embed(spec, prefix=PREFIX))

# ─── COMMANDES ÉTUDIANT ───────────────────────────────────────────────────────
@bot.command(name='joinA', help=messages.JOIN['A']['description_template'])
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(embed=build_embed(messages.ERRORS['permission_denied']))
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    await ctx.send(embed=build_embed(messages.JOIN['A'], user_mention=user.mention))

@bot.command(name='joinB', help=messages.JOIN['B']['description_template'])
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(embed=build_embed(messages.ERRORS['permission_denied']))
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id, 'B')
    role = await ensure_role(ctx.guild, POMO_ROLE_B)
    await user.add_roles(role)
    await ctx.send(embed=build_embed(messages.JOIN['B'], user_mention=user.mention))

@bot.command(name='leave', help=messages.LEAVE['description_template'])
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(embed=build_embed(messages.ERRORS['permission_denied']))
    now_ts = datetime.now(timezone.utc).timestamp()
    mins = max(int((now_ts - join_ts)//60), 1)
    ajouter_temps(user.id, ctx.guild.id, mins)
    if mode == 'A': PARTICIPANTS_A.discard(user.id); role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_A)
    else:            PARTICIPANTS_B.discard(user.id); role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_B)
    if role: await user.remove_roles(role)
    await ctx.send(embed=build_embed(messages.LEAVE, user_mention=user.mention, minutes=mins))

@bot.command(name='time', help=messages.TIME_LEFT['description_template'])
@check_maintenance()
async def time_left(ctx):
    if not SESSION_ACTIVE or SESSION_PHASE is None:
        return await ctx.send(embed=build_embed(messages.ERRORS['permission_denied']))
    now = datetime.now(timezone.utc)
    rem = SESSION_END - now
    m, s = divmod(max(int(rem.total_seconds()),0), 60)
    nxt = 'pause' if SESSION_PHASE=='work' else 'travail'
    await ctx.send(embed=build_embed(
        messages.TIME_LEFT,
        phase=SESSION_PHASE,
        next_phase=nxt,
        minutes=m,
        seconds=s
    ))

@bot.command(name='status', help=messages.STATUS['fields'][0]['value_template'])
async def status(ctx):
    latency = round(bot.latency*1000)
    now_utc = datetime.now(timezone.utc)
    lausanne = now_utc.astimezone(ZoneInfo('Europe/Zurich')).strftime("%Y-%m-%d %H:%M:%S")
    if SESSION_ACTIVE and SESSION_END:
        rem = max(int((SESSION_END-now_utc).total_seconds()),0)
        m, s = divmod(rem, 60)
        sess = f"{SESSION_PHASE} dans {m} min {s} sec"
    else:
        sess = "aucune session active"
    await ctx.send(embed=build_embed(
        messages.STATUS,
        latency=f"{latency} ms",
        local_time=lausanne,
        session_status=sess
    ))

@bot.command(name='stats', help=messages.STATS['fields'][0]['value_template'])
@check_maintenance()
async def stats(ctx):
    db = TinyDB('leaderboard.json').table(str(ctx.guild.id)).all()
    total = sum(u['minutes'] for u in db)
    count = len(db)
    avg = (total/count) if count else 0
    await ctx.send(embed=build_embed(
        messages.STATS,
        unique_users=str(count),
        total_minutes=str(total),
        average_minutes=avg
    ))

@bot.command(name='leaderboard', help="Top 5 général")
@check_maintenance()
async def leaderboard(ctx):
    top5 = classement_top10(ctx.guild.id)[:5]
    e = discord.Embed(title=messages.LEADERBOARD['title'],
                      color=messages.LEADERBOARD['color'])
    if not top5:
        e.description = "Aucun utilisateur."
    else:
        for i, (uid, m) in enumerate(top5, 1):
            user = await bot.fetch_user(uid)
            e.add_field(
                name=messages.LEADERBOARD['entry_template']['name_template'].format(rank=i, username=user.name),
                value=messages.LEADERBOARD['entry_template']['value_template'].format(minutes=m),
                inline=False
            )
    await ctx.send(embed=e)

# ─── COMMANDES ADMIN ─────────────────────────────────────────────────────────
@bot.command(name='maintenance', help="Mode maintenance on/off")
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    await ctx.send(embed=build_embed(
        messages.MAINT_TOGGLE,
        state=state
    ))

@bot.command(name='set_channel', help="Choisir canal (admin)")
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini','w') as f: config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    await ctx.send(embed=build_embed(
        messages.SET_CHANNEL,
        channel_mention=channel.mention
    ))

@bot.command(name='set_role_A', help="Définir rôle A (admin)")
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global POMO_ROLE_A
    POMO_ROLE_A = role.name
    await ctx.send(embed=build_embed(
        messages.SET_ROLE_A,
        role_mention=role.mention
    ))

@bot.command(name='set_role_B', help="Définir rôle B (admin)")
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global POMO_ROLE_B
    POMO_ROLE_B = role.name
    await ctx.send(embed=build_embed(
        messages.SET_ROLE_B,
        role_mention=role.mention
    ))

@bot.command(name='clear_stats', help="Réinitialiser toutes les stats")
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    await ctx.send(embed=build_embed(messages.CLEAR_STATS))

@bot.command(name='help', help="Affiche ce message")
async def help_cmd(ctx):
    await ctx.send(embed=build_embed(messages.HELP))

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    if not channel or not (PARTICIPANTS_A or PARTICIPANTS_B):
        return

    # Méthode A
    if PARTICIPANTS_A:
        SESSION_ACTIVE = True
        SESSION_PHASE = 'work'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=WORK_TIME_A)
        role_mention = (await ensure_role(channel.guild, POMO_ROLE_A)).mention
        await channel.send(messages.LOOP['start_template'].format(mode='A', duration=WORK_TIME_A, role_mention=role_mention))
        await asyncio.sleep(WORK_TIME_A*60)
        SESSION_PHASE = 'break'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=BREAK_TIME_A)
        await channel.send(messages.LOOP['pause_template'].format(mode='A', duration=BREAK_TIME_A, role_mention=role_mention))
        await asyncio.sleep(BREAK_TIME_A*60)
        for uid in PARTICIPANTS_A:
            ajouter_temps(uid, channel.guild.id, WORK_TIME_A)
        SESSION_ACTIVE = False

    # Méthode B
    if PARTICIPANTS_B:
        SESSION_ACTIVE = True
        SESSION_PHASE = 'work'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=WORK_TIME_B)
        role_mention = (await ensure_role(channel.guild, POMO_ROLE_B)).mention
        await channel.send(messages.LOOP['start_template'].format(mode='B', duration=WORK_TIME_B, role_mention=role_mention))
        await asyncio.sleep(WORK_TIME_B*60)
        SESSION_PHASE = 'break'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=BREAK_TIME_B)
        await channel.send(messages.LOOP['pause_template'].format(mode='B', duration=BREAK_TIME_B, role_mention=role_mention))
        await asyncio.sleep(BREAK_TIME_B*60)
        for uid in PARTICIPANTS_B:
            ajouter_temps(uid, channel.guild.id, WORK_TIME_B)
        SESSION_ACTIVE = False

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
