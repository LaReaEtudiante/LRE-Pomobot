import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
import logging
from enum import Enum
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

# -------------------- CONFIGURATION & GLOBALS --------------------
config = configparser.ConfigParser()
config.read('settings.ini')

# Méthode A (50–10) et B (25–5)
WORK_TIME_A  = config['CURRENT_SETTINGS'].getint('work_time_A', fallback=50)
BREAK_TIME_A = config['CURRENT_SETTINGS'].getint('break_time_A', fallback=10)
POMO_ROLE_A  = config['CURRENT_SETTINGS'].get('pomodoro_role_A',   fallback='50-10')
WORK_TIME_B  = config['CURRENT_SETTINGS'].getint('work_time_B', fallback=25)
BREAK_TIME_B = config['CURRENT_SETTINGS'].getint('break_time_B', fallback=5)
POMO_ROLE_B  = config['CURRENT_SETTINGS'].get('pomodoro_role_B',   fallback='25-5')

# Canal de publication
POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)

# Préfixe et bot
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

# Logging
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# États de session
SESSION_ACTIVE = False
SESSION_PHASE  = None  # 'work' or 'break'
SESSION_END    = None
PARTICIPANTS_A = set()
PARTICIPANTS_B = set()

# Couleurs pour embeds
class MsgColors(Enum):
    AQUA   = 0x33c6bb
    YELLOW = 0xFFD966
    RED    = 0xEA3546
    PURPLE = 0x6040b1

# -------------------- UTILS --------------------
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

# -------------------- ÉVÉNEMENTS --------------------
@bot.event
async def on_ready():
    global MAINTENANCE_MODE
    logger.info(f"{bot.user} connecté.")

    # Charger participants persistés
    for guild in bot.guilds:
        for uid, mode in get_all_participants(guild.id):
            if mode == 'A':
                PARTICIPANTS_A.add(uid)
            elif mode == 'B':
                PARTICIPANTS_B.add(uid)

    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    e = discord.Embed(color=MsgColors.RED.value)
    if isinstance(error, commands.CommandNotFound):
        e.title = "❓ Commande inconnue"
        e.description = f"Tapez `{PREFIX}help` pour voir la liste."
    elif isinstance(error, commands.CommandError) and str(error) == "Bot en mode maintenance.":
        e.title = "⚠️ Maintenance"
        e.description = "Le bot est en maintenance."
    elif isinstance(error, commands.MissingRequiredArgument):
        e.title = "❗ Argument manquant"
        e.description = "Vérifiez la syntaxe de la commande."
    elif isinstance(error, commands.CheckFailure):
        e.title = "🚫 Permission refusée"
        e.description = "Vous n'avez pas les droits requis."
    else:
        e.title = "❌ Erreur inattendue"
        e.description = str(error)
        logger.error(f"Erreur inattendue: {error}")
    await ctx.send(embed=e)

# -------------------- COMMANDES ÉTUDIANT --------------------
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit.",
            color=MsgColors.YELLOW.value
        ))
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a rejoint (mode A – 50-10).",
        color=MsgColors.AQUA.value
    ))

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit.",
            color=MsgColors.YELLOW.value
        ))
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id, 'B')
    role = await ensure_role(ctx.guild, POMO_ROLE_B)
    await user.add_roles(role)
    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a rejoint (mode B – 25-5).",
        color=MsgColors.AQUA.value
    ))

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(embed=discord.Embed(
            description=f"{user.mention} n'était pas inscrit.",
            color=MsgColors.YELLOW.value
        ))

    now_ts = datetime.now(timezone.utc).timestamp()
    secs = now_ts - join_ts
    mins = max(int(secs // 60), 1)
    ajouter_temps(user.id, ctx.guild.id, mins)

    if mode == 'A':
        PARTICIPANTS_A.discard(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_A)
    else:
        PARTICIPANTS_B.discard(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_B)

    if role:
        await user.remove_roles(role)

    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a quitté. +{mins} min ajoutées.",
        color=MsgColors.AQUA.value
    ))

@bot.command(name='time', help='Temps restant session')
@check_maintenance()
async def time_left(ctx):
    if not SESSION_ACTIVE or SESSION_PHASE is None:
        return await ctx.send(embed=discord.Embed(
            description="Aucune session en cours.",
            color=MsgColors.YELLOW.value
        ))
    now = datetime.now(timezone.utc)
    rem = SESSION_END - now
    secs = max(int(rem.total_seconds()), 0)
    m, s = divmod(secs, 60)
    phase = 'travail' if SESSION_PHASE == 'work' else 'pause'
    nxt = 'pause' if SESSION_PHASE == 'work' else 'travail'
    e = discord.Embed(
        title=f"⏱ Session {phase}",
        description=f"La {nxt} commence dans **{m}** min et **{s}** sec.",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=e)

# -------------------- COMMANDE STATUS --------------------
@bot.command(name='status', help='Afficher latence et état du bot')
async def status(ctx):
    latency = round(bot.latency * 1000)
    now_utc = datetime.now(timezone.utc)
    lausanne = now_utc.astimezone(ZoneInfo('Europe/Zurich'))
    if SESSION_ACTIVE and SESSION_END:
        rem = max(int((SESSION_END - now_utc).total_seconds()), 0)
        m, s = divmod(rem, 60)
        sess = f"{SESSION_PHASE} dans {m} min {s} sec"
    else:
        sess = "aucune session active"
    e = discord.Embed(title="🔍 État du bot", color=MsgColors.PURPLE.value)
    e.add_field(name="Latence", value=f"{latency} ms", inline=True)
    e.add_field(name="Heure (Lausanne)", value=lausanne.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
    e.add_field(name="Session", value=sess, inline=False)
    await ctx.send(embed=e)

# -------------------- STATS & LEADERBOARD --------------------
@bot.command(name='stats', help='Vos stats')
@check_maintenance()
async def stats(ctx):
    db = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    all_ = db.all()
    total = sum(u['minutes'] for u in all_)
    count = len(all_)
    avg = (total / count) if count else 0
    e = discord.Embed(title="📊 Stats Pomodoro", color=MsgColors.AQUA.value)
    e.add_field(name="Utilisateurs uniques",            value=str(count),      inline=False)
    e.add_field(name="Temps total (min)",               value=str(total),      inline=False)
    e.add_field(name="Moyenne/utilisateur (min)",       value=f"{avg:.1f}",    inline=False)
    await ctx.send(embed=e)

@bot.command(name='leaderboard', help='Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top = classement_top10(ctx.guild.id)[:5]
    e = discord.Embed(title="🏆 Leaderboard Pomodoro", color=MsgColors.PURPLE.value)
    if not top:
        e.description = "Aucun utilisateur."
    else:
        for i, (uid, m) in enumerate(top, 1):
            user = await ctx.bot.fetch_user(uid)
            e.add_field(name=f"#{i} {user.name}", value=f"{m} min", inline=False)
    await ctx.send(embed=e)

# -------------------- ADMIN --------------------
@bot.command(name='maintenance', help='Mode maintenance on/off')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    e = discord.Embed(title="🔧 Maintenance", description=state, color=MsgColors.YELLOW.value)
    await ctx.send(embed=e)

@bot.command(name='set_channel', help='Choisir canal (admin)')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    await ctx.send(embed=discord.Embed(
        description=f"Canal défini sur {channel.mention}",
        color=MsgColors.AQUA.value
    ))

@bot.command(name='set_role_A', help='Définir rôle A (admin)')
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMO_ROLE_A
    POMO_ROLE_A = role.name
    await ctx.send(embed=discord.Embed(
        description=f"Rôle A défini sur {role.mention}",
        color=MsgColors.AQUA.value
    ))

@bot.command(name='set_role_B', help='Définir rôle B (admin)')
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMO_ROLE_B
    POMO_ROLE_B = role.name
    await ctx.send(embed=discord.Embed(
        description=f"Rôle B défini sur {role.mention}",
        color=MsgColors.AQUA.value
    ))

@bot.command(name='clear_stats', help='Réinitialiser toutes les stats')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    await ctx.send(embed=discord.Embed(
        description="Statistiques réinitialisées.",
        color=MsgColors.YELLOW.value
    ))

# -------------------- NOUVELLE HELP ÉTUDIANT --------------------
@bot.command(name='help', help='Liste des commandes étudiantes')
async def help_cmd(ctx):
    e = discord.Embed(title="📚 Commandes Pomodoro", color=MsgColors.PURPLE.value)
    e.add_field(name="Étudiant", value=(
        "`joinA`       – rejoindre A (50-10)\n"
        "`joinB`       – rejoindre B (25-5)\n"
        "`leave`       – quitter\n"
        "`time`        – temps restant\n"
        "`status`      – état du bot\n"
        "`stats`       – vos stats\n"
        "`leaderboard` – top 5"
    ), inline=False)
    await ctx.send(embed=e)

# -------------------- BOUCLE POMODORO --------------------
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    cid = POMODORO_CHANNEL_ID
    channel = bot.get_channel(cid) if cid else None
    if not channel or not (PARTICIPANTS_A or PARTICIPANTS_B):
        return

    # méthode A
    if PARTICIPANTS_A:
        SESSION_ACTIVE = True
        SESSION_PHASE = 'work'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=WORK_TIME_A)
        mention = (await ensure_role(channel.guild, POMO_ROLE_A)).mention
        await channel.send(f"Début travail (A, {WORK_TIME_A} min) ! {mention}")
        await asyncio.sleep(WORK_TIME_A * 60)
        SESSION_PHASE = 'break'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=BREAK_TIME_A)
        await channel.send(f"Début pause (A, {BREAK_TIME_A} min) ! {mention}")
        await asyncio.sleep(BREAK_TIME_A * 60)
        SESSION_ACTIVE = False

    # méthode B
    if PARTICIPANTS_B:
        SESSION_ACTIVE = True
        SESSION_PHASE = 'work'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=WORK_TIME_B)
        mention = (await ensure_role(channel.guild, POMO_ROLE_B)).mention
        await channel.send(f"Début travail (B, {WORK_TIME_B} min) ! {mention}")
        await asyncio.sleep(WORK_TIME_B * 60)
        SESSION_PHASE = 'break'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=BREAK_TIME_B)
        await channel.send(f"Début pause (B, {BREAK_TIME_B} min) ! {mention}")
        await asyncio.sleep(BREAK_TIME_B * 60)
        SESSION_ACTIVE = False

# -------------------- MAIN --------------------
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
