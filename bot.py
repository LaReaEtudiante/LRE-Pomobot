import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
from enum import Enum
from database import ajouter_temps, recuperer_temps, classement_top10
from keep_alive import keep_alive
import logging
from tinydb import TinyDB
from datetime import datetime, timezone, timedelta

# -- CONFIG & GLOBALS --
DEBUG = True
MAINTENANCE_MODE = False
SESSION_ACTIVE = False
SESSION_PHASE = None  # 'work' or 'break'
SESSION_END = None

# Liste des IDs des participants au Pomodoro
PARTICIPANTS = []

# Charger configuration
config = configparser.ConfigParser()
config.read('settings.ini')
WORK_TIME = int(config['CURRENT_SETTINGS']['work_time'])
BREAK_TIME = int(config['CURRENT_SETTINGS']['break_time'])
POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
POMODORO_ROLE_NAME = config['CURRENT_SETTINGS'].get('pomodoro_role', '50-10')

# Bot setup
discord_token = os.getenv('DISCORD_TOKEN')
intents = discord.Intents.default()
intents.message_content = True
prefix = config['CURRENT_SETTINGS'].get('prefix', '*')
bot = commands.Bot(command_prefix=prefix, help_command=None, intents=intents)

# Logging
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# Colors
class MsgColors(Enum):
    AQUA = 0x33c6bb
    YELLOW = 0xFFD966
    RED = 0xEA3546
    PURPLE = 0x6040b1

# Checks
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def check_maintenance_mode():
    async def predicate(ctx):
        if MAINTENANCE_MODE and ctx.command.name != 'maintenance':
            raise commands.CommandError("Bot en mode maintenance.")
        return True
    return commands.check(predicate)

# Ensure role exists and return mention
async def get_role_mention(guild: discord.Guild) -> str:
    role = discord.utils.get(guild.roles, name=POMODORO_ROLE_NAME)
    if role is None:
        role = await guild.create_role(name=POMODORO_ROLE_NAME)
        logger.info(f"Rôle '{POMODORO_ROLE_NAME}' créé dans {guild.name}")
    return role.mention

# -------------------- EVENTS --------------------
@bot.event
async def on_command_error(ctx, error):
    # Commande non trouvée
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"Commande inconnue. Tapez `{prefix}help` pour voir la liste des commandes.")
    # Mode maintenance
    elif isinstance(error, commands.CommandError) and str(error) == "Bot en mode maintenance.":
        await ctx.send("Le bot est actuellement en maintenance. Veuillez réessayer plus tard.")
    # Argument manquant
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Argument manquant. Veuillez vérifier la commande.")
    # Permissions insuffisantes
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("Vous n'avez pas la permission d'utiliser cette commande.")
    # Autres erreurs inattendues
    else:
        await ctx.send(f"Une erreur inattendue est survenue : {error}")
        logger.error(f"Erreur lors de l'exécution de la commande : {error}")

# -------------------- COMMANDS --------------------
@bot.command(name='maintenance', help='Activer/désactiver maintenance')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = 'maintenance' if MAINTENANCE_MODE else 'normal'
    await ctx.send(f"Mode {state}.")

@bot.command(name='join', help='Rejoindre le Pomodoro')
@check_maintenance_mode()
async def join(ctx):
    user = ctx.author
    if user.id not in PARTICIPANTS:
        PARTICIPANTS.append(user.id)
        mention = await get_role_mention(ctx.guild)
        await user.add_roles(discord.utils.get(ctx.guild.roles, name=POMODORO_ROLE_NAME))
        await ctx.send(f"{user.mention} a rejoint le Pomodoro.")
    else:
        await ctx.send(f"{user.mention} est déjà inscrit.")

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance_mode()
async def leave(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS:
        PARTICIPANTS.remove(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMODORO_ROLE_NAME)
        if role:
            await user.remove_roles(role)
        await ctx.send(f"{user.mention} a quitté le Pomodoro.")
    else:
        await ctx.send(f"{user.mention} n'était pas inscrit.")

@bot.command(name='time', help='Temps restant de la session en cours')
@check_maintenance_mode()
async def time_left(ctx):
    if not SESSION_ACTIVE or SESSION_PHASE is None:
        return await ctx.send("Aucune session Pomodoro en cours.")
    now = datetime.now(timezone.utc)
    remaining = SESSION_END - now
    mins, secs = divmod(max(int(remaining.total_seconds()),0), 60)
    phase = 'travail' if SESSION_PHASE == 'work' else 'pause'
    next_phase = 'pause' if SESSION_PHASE == 'work' else 'travail'
    await ctx.send(f"Vous êtes en session de {phase}. La {next_phase} commence dans {mins} min et {secs} sec.")

@bot.command(name='ping', help='Vérifie la latence du bot')
async def ping(ctx):
    await ctx.send(f"Pong ! Latence : {round(bot.latency*1000)} ms")

@bot.command(name='stats', help='Voir statistiques d’utilisation')
@check_maintenance_mode()
async def stats(ctx):
    db = TinyDB('leaderboard.json')
    table = db.table(str(ctx.guild.id))
    users = table.all()
    total = sum(u['minutes'] for u in users) if users else 0
    count = len(users)
    avg = (total / count) if count else 0
    embed = discord.Embed(title="📊 Stats Pomodoro", color=MsgColors.AQUA.value)
    embed.add_field(name="Utilisateurs uniques", value=str(count))
    embed.add_field(name="Temps total (min)", value=str(total))
    embed.add_field(name="Moyenne par user", value=f"{avg:.1f} min")
    await ctx.send(embed=embed)

@bot.command(name='help', help='Affiche ce message')
async def help_cmd(ctx):
    cmds = '\n'.join(f"**{c.name}**: {c.help or ''}" for c in bot.commands)
    await ctx.send(embed=discord.Embed(title="Commandes disponibles", description=cmds, color=MsgColors.PURPLE.value))

@bot.command(name='set_channel', help='Choisir canal Pomodoro (admin)')
@is_admin()
async def set_channel_cmd(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini', 'w') as f: config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    await ctx.send(f"Canal Pomodoro défini sur {channel.mention}")

@bot.command(name='set_role', help='Choisir rôle Pomodoro (admin)')
@is_admin()
async def set_role_cmd(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role'] = role.name
    with open('settings.ini', 'w') as f: config.write(f)
    global POMODORO_ROLE_NAME
    POMODORO_ROLE_NAME = role.name
    await ctx.send(f"Rôle Pomodoro défini sur {role.name}")

# -------------------- POMODORO LOOP --------------------
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    work = int(config['CURRENT_SETTINGS']['work_time'])
    brk = int(config['CURRENT_SETTINGS']['break_time'])
    cid = POMODORO_CHANNEL_ID or None
    channel = bot.get_channel(cid) if cid else None
    if not channel:
        return
    # Début session travail
    SESSION_ACTIVE = True
    SESSION_PHASE = 'work'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=work)
    mention = await get_role_mention(channel.guild)
    await channel.send(f"Début travail ({work} min) ! {mention}")
    for minute in range(work):
        await asyncio.sleep(60)
        if minute % 5 == 0:
            rem = work - minute - 1
            await channel.send(f"{rem} minutes restantes.")
    # Début session pause
    SESSION_PHASE = 'break'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=brk)
    mention = await get_role_mention(channel.guild)
    await channel.send(f"Début pause ({brk} min) ! {mention}")
    for _ in range(brk):
        await asyncio.sleep(60)
    # Enregistrer temps de travail
    for uid in PARTICIPANTS:
        ajouter_temps(uid, channel.guild.id, work)
    logger.info(f"Temps ajouté pour participants: {PARTICIPANTS}")
    SESSION_ACTIVE = False

# -------------------- MAIN --------------------
if __name__ == '__main__':
    keep_alive()
    bot.run(discord_token)
