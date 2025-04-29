import os
import time
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
from enum import Enum
from database import (
    ajouter_temps,
    classement_top10,
    add_participant,
    remove_participant
)
from keep_alive import keep_alive
import logging
from tinydb import TinyDB
from datetime import datetime, timezone, timedelta

# -- CONFIGURATION & GLOBALS --
config = configparser.ConfigParser()
config.read('settings.ini')

# Méthode A (50–10) et B (25–5)
WORK_TIME_A     = config['CURRENT_SETTINGS'].getint('work_time_A',   fallback=50)
BREAK_TIME_A    = config['CURRENT_SETTINGS'].getint('break_time_A',  fallback=10)
POMO_ROLE_A     = config['CURRENT_SETTINGS'].get('pomodoro_role_A', fallback='50-10')
WORK_TIME_B     = config['CURRENT_SETTINGS'].getint('work_time_B',   fallback=25)
BREAK_TIME_B    = config['CURRENT_SETTINGS'].getint('break_time_B',  fallback=5)
POMO_ROLE_B     = config['CURRENT_SETTINGS'].get('pomodoro_role_B', fallback='25-5')

# Canal de publication
POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)

# Préfixe et bot
PREFIX = config['CURRENT_SETTINGS'].get('prefix','*')
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

# États de session pour chaque mode
SESSION_RUNNING_A = False
SESSION_RUNNING_B = False

# Participants en mémoire
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

async def run_session_A():
    global SESSION_RUNNING_A
    if SESSION_RUNNING_A: 
        return
    SESSION_RUNNING_A = True

    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    if not channel:
        SESSION_RUNNING_A = False
        return

    role_mention = (await ensure_role(channel.guild, POMO_ROLE_A)).mention
    # Travail
    await channel.send(f"Début travail (A, {WORK_TIME_A} min) ! {role_mention}")
    await asyncio.sleep(WORK_TIME_A * 60)
    # Pause
    await channel.send(f"Début pause (A, {BREAK_TIME_A} min) ! {role_mention}")
    await asyncio.sleep(BREAK_TIME_A * 60)
    # Ajouter le temps fixe pour ceux qui sont restés
    for uid in list(PARTICIPANTS_A):
        ajouter_temps(uid, channel.guild.id, WORK_TIME_A)

    SESSION_RUNNING_A = False

async def run_session_B():
    global SESSION_RUNNING_B
    if SESSION_RUNNING_B:
        return
    SESSION_RUNNING_B = True

    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    if not channel:
        SESSION_RUNNING_B = False
        return

    role_mention = (await ensure_role(channel.guild, POMO_ROLE_B)).mention
    # Travail
    await channel.send(f"Début travail (B, {WORK_TIME_B} min) ! {role_mention}")
    await asyncio.sleep(WORK_TIME_B * 60)
    # Pause
    await channel.send(f"Début pause (B, {BREAK_TIME_B} min) ! {role_mention}")
    await asyncio.sleep(BREAK_TIME_B * 60)
    # Ajouter le temps fixe pour ceux qui sont restés
    for uid in list(PARTICIPANTS_B):
        ajouter_temps(uid, channel.guild.id, WORK_TIME_B)

    SESSION_RUNNING_B = False

# -------------------- SCHEDULER MINUTIER --------------------
@tasks.loop(minutes=1)
async def pomodoro_scheduler():
    if PARTICIPANTS_A and not SESSION_RUNNING_A:
        await run_session_A()
    if PARTICIPANTS_B and not SESSION_RUNNING_B:
        await run_session_B()

# -------------------- ÉVÉNEMENTS --------------------
@bot.event
async def on_ready():
    global MAINTENANCE_MODE
    logger.info(f"{bot.user} connecté.")
    if not pomodoro_scheduler.is_running():
        pomodoro_scheduler.start()

@bot.event
async def on_command_error(ctx, error):
    e = discord.Embed(color=MsgColors.RED.value)
    if isinstance(error, commands.CommandNotFound):
        e.title = "❓ Commande inconnue"
        e.description = f"Tapez `{PREFIX}help` pour voir la liste."
    elif isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance.":
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
        logger.error(f"Erreur: {error!r}")
    await ctx.send(embed=e)

# -------------------- COMMANDES ÉTUDIANT --------------------
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    guild_id = ctx.guild.id
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit.", color=MsgColors.YELLOW.value))

    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, guild_id)
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a rejoint (mode A – 50-10).", color=MsgColors.AQUA.value))

    # démarrage immédiat si c'est le premier inscrit
    if len(PARTICIPANTS_A) == 1:
        asyncio.create_task(run_session_A())

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    guild_id = ctx.guild.id
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit.", color=MsgColors.YELLOW.value))

    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, guild_id)
    role = await ensure_role(ctx.guild, POMO_ROLE_B)
    await user.add_roles(role)
    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a rejoint (mode B – 25-5).", color=MsgColors.AQUA.value))

    if len(PARTICIPANTS_B) == 1:
        asyncio.create_task(run_session_B())

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user     = ctx.author
    guild_id = ctx.guild.id
    join_ts  = remove_participant(user.id, guild_id)
    if join_ts is None:
        return await ctx.send(embed=discord.Embed(
            description=f"{user.mention} n'était pas inscrit.",
            color=MsgColors.YELLOW.value))

    # calcul de la durée réelle passée
    now_ts   = datetime.now(timezone.utc).timestamp()
    seconds  = max(0, now_ts - join_ts)
    minutes  = max(1, int(seconds // 60))

    # retrait du rôle et de l'ensemble
    if user.id in PARTICIPANTS_A:
        PARTICIPANTS_A.remove(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_A)
    else:
        PARTICIPANTS_B.remove(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_B)
    if role:
        await user.remove_roles(role)

    # on stocke le temps réel
    ajouter_temps(user.id, guild_id, minutes)
    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a quitté. +{minutes} min ajoutées.",
        color=MsgColors.AQUA.value))

@bot.command(name='time', help='Temps restant session')
@check_maintenance()
async def time_left(ctx):
    # on laisse l'implémentation actuelle pour la V3.1.20
    await ctx.send("➖ fonction `*time` inchangée pour maintenant.")

# -------------------- COMMANDE RESTART --------------------
@bot.command(name='restart', help='Redémarrer la session Pomodoro manuellement')
@is_admin()
async def restart(ctx):
    launched = False
    if PARTICIPANTS_A and not SESSION_RUNNING_A:
        asyncio.create_task(run_session_A())
        launched = True
    if PARTICIPANTS_B and not SESSION_RUNNING_B:
        asyncio.create_task(run_session_B())
        launched = True

    if launched:
        await ctx.send(embed=discord.Embed(
            description="✅ Sessions relancées manuellement.", color=MsgColors.AQUA.value))
    else:
        await ctx.send(embed=discord.Embed(
            description="⚠️ Aucune session à relancer.", color=MsgColors.YELLOW.value))

# -------------------- COMMANDES COMMUNES --------------------
MAINTENANCE_MODE = False

@bot.command(name='stats', help='Vos stats')
@check_maintenance()
async def stats(ctx):
    db    = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    total = sum(u['minutes'] for u in db.all())
    users = len(db.all())
    avg   = (total / users if users else 0)
    e = discord.Embed(title="📊 Stats Pomodoro", color=MsgColors.AQUA.value)
    e.add_field(name="Utilisateurs uniques", value=str(users), inline=False)
    e.add_field(name="Temps total (min)",      value=str(total), inline=False)
    e.add_field(name="Moyenne/utilisateur (min)", value=f"{avg:.1f}", inline=False)
    await ctx.send(embed=e)

@bot.command(name='leaderboard', help='Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top = classement_top10(ctx.guild.id)[:5]
    e = discord.Embed(title="🏆 Leaderboard Pomodoro", color=MsgColors.PURPLE.value)
    if not top:
        e.description = "Aucun utilisateur."
    else:
        for i, (uid, m) in enumerate(top, start=1):
            user = await bot.fetch_user(uid)
            e.add_field(name=f"#{i} {user.name}", value=f"{m} min", inline=False)
    await ctx.send(embed=e)

@bot.command(name='maintenance', help='Mode maintenance on/off')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    await ctx.send(embed=discord.Embed(
        title="🔧 Maintenance", description=state, color=MsgColors.YELLOW.value))

@bot.command(name='help', help='Affiche ce message')
async def help_cmd(ctx):
    e = discord.Embed(title="🛠️ Commandes Pomodoro", color=MsgColors.PURPLE.value)
    e.add_field(name="Étudiant", value=(
        "`joinA`       – rejoindre A (50-10)\n"
        "`joinB`       – rejoindre B (25-5)\n"
        "`leave`       – quitter (calcul réel)\n"
        "`time`        – temps restant (idem)\n"
        "`stats`       – vos stats\n"
        "`leaderboard` – top 5"
    ), inline=False)
    e.add_field(name="Admin", value=(
        "`restart`     – relancer sessions immédiatement\n"
        "`maintenance` – on/off\n"
        "`help`        – ce message"
    ), inline=False)
    await ctx.send(embed=e)

# -------------------- MAIN --------------------
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
