import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
from enum import Enum
from database import ajouter_temps, add_participant, remove_participant, classement_top10
from keep_alive import keep_alive
import logging
from tinydb import TinyDB
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo  # stdlib depuis Python 3.9

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
intents.message_content = True  # indispensable pour lire les commandes en message
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
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

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
        logger.error(f"Erreur: {error}")
    await ctx.send(embed=e)

# -------------------- COMMANDES ÉTUDIANT --------------------
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit.", color=MsgColors.YELLOW.value))
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id)
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a rejoint (mode A – 50-10).",
        color=MsgColors.AQUA.value))

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit.", color=MsgColors.YELLOW.value))
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id)
    role = await ensure_role(ctx.guild, POMO_ROLE_B)
    await user.add_roles(role)
    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a rejoint (mode B – 25-5).",
        color=MsgColors.AQUA.value))

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    # récupère timestamp join et supprime participant
    ts = remove_participant(user.id, ctx.guild.id)
    if ts is None:
        return await ctx.send(embed=discord.Embed(
            description=f"{user.mention} n'était pas inscrit.",
            color=MsgColors.YELLOW.value))
    # calcule durée réelle en minutes arrondies
    minutes_spent = int((datetime.now(timezone.utc).timestamp() - ts) // 60)
    # détermine mode et ajoute
    if user.id in PARTICIPANTS_A:
        PARTICIPANTS_A.remove(user.id)
        ajouter_temps(user.id, ctx.guild.id, minutes_spent)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_A)
    else:
        PARTICIPANTS_B.remove(user.id)
        ajouter_temps(user.id, ctx.guild.id, minutes_spent)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_B)
    if role:
        await user.remove_roles(role)
    await ctx.send(embed=discord.Embed(
        description=f"{user.mention} a quitté. +{minutes_spent} min ajoutées.",
        color=MsgColors.AQUA.value))

# les autres commandes (`time`, `status`, `stats`, `leaderboard`, `maintenance`, `set_*`, `help`)
# restent inchangées, on ne les renvoie pas si elles sont déjà ok.

# -------------------- BOUCLE POMODORO --------------------
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    cid = POMODORO_CHANNEL_ID
    channel = bot.get_channel(cid) if cid else None
    if not channel or not (PARTICIPANTS_A or PARTICIPANTS_B):
        return
    # ... ton code existant pour démarrer travail/pause et logger ...

# -------------------- MAIN --------------------
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
