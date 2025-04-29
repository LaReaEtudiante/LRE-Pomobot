# bot.py
import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
from enum import Enum
from database import (
    ajouter_temps, remove_participant,
    get_all_participants, add_participant,
    classement_top10
)
from keep_alive import keep_alive
import logging
from datetime import datetime, timezone, timedelta

# — CONFIG & GLOBALS —
config = configparser.ConfigParser()
config.read('settings.ini')

prefix   = config['CURRENT_SETTINGS'].get('prefix', '*')
BOT_TOKEN= os.getenv('DISCORD_TOKEN')
WORK    = int(config['CURRENT_SETTINGS']['work_time'])
BREAK   = int(config['CURRENT_SETTINGS']['break_time'])
CHAN_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
ROLE    = config['CURRENT_SETTINGS'].get('pomodoro_role', '50-10')

DEBUG = True
SESSION_ACTIVE = False
SESSION_PHASE  = None   # 'work' ou 'break'
SESSION_END    = None

# Liste temporaire (chargée depuis DB au démarrage)
PARTICIPANTS = []

# — BOT SETUP —
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=prefix,
    help_command=None,
    intents=intents,
    case_insensitive=True    # <— E1
)

# — LOGGING —
logger = logging.getLogger('pomobot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# — COLORS —
class MsgColors(Enum):
    AQUA   = 0x33c6bb
    PURPLE = 0x6040b1

# — CHECKS —
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def check_maintenance_mode():
    async def predicate(ctx):
        # implémenter si besoin un flag de maintenance
        return True
    return commands.check(predicate)

# — UTILS —
async def get_role_mention(guild: discord.Guild) -> str:
    role = discord.utils.get(guild.roles, name=ROLE)
    if role is None:
        role = await guild.create_role(name=ROLE)
        logger.info(f"Rôle '{ROLE}' créé dans {guild.name}")
    return role.mention

# — EVENTS —
@bot.event
async def on_ready():
    logger.info(f"{bot.user} connecté.")
    # Charger la liste persistée des participants (A2)
    if CHAN_ID:
        chan = bot.get_channel(CHAN_ID)
        if chan:
            guild = chan.guild
            PARTICIPANTS.clear()
            PARTICIPANTS.extend(get_all_participants(guild.id))
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return await ctx.send(f"Commande inconnue. Tapez `{prefix}help`.")
    await ctx.send(f"Erreur : {error}")
    logger.error(error)

# — COMMANDES —
@bot.command(name='join', help='Rejoindre le Pomodoro')
@check_maintenance_mode()
async def join(ctx):
    uid = ctx.author.id
    gid = ctx.guild.id
    if uid in PARTICIPANTS:
        return await ctx.send(f"{ctx.author.mention} déjà inscrit·e.")
    PARTICIPANTS.append(uid)
    add_participant(uid, gid)   # A2 + A3
    role = discord.utils.get(ctx.guild.roles, name=ROLE)
    await ctx.author.add_roles(role)
    await ctx.send(f"{ctx.author.mention} a rejoint le Pomodoro.")

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance_mode()
async def leave(ctx):
    uid = ctx.author.id
    gid = ctx.guild.id
    if uid not in PARTICIPANTS:
        return await ctx.send(f"{ctx.author.mention} n’était pas inscrit·e.")
    PARTICIPANTS.remove(uid)
    # Calcul du temps passé depuis join (A1)
    join_ts = remove_participant(uid, gid)
    if join_ts:
        elapsed = int((datetime.now(timezone.utc).timestamp() - join_ts) / 60)
        ajouter_temps(uid, gid, elapsed)
        await ctx.send(f"{ctx.author.mention} quitté. Temps ajouté : {elapsed} min.")
    else:
        await ctx.send(f"{ctx.author.mention} quitté sans timestamp connu.")
    role = discord.utils.get(ctx.guild.roles, name=ROLE)
    if role:
        await ctx.author.remove_roles(role)

@bot.command(name='time', help='Temps restant de la session en cours')
@check_maintenance_mode()
async def time_left(ctx):
    if not SESSION_ACTIVE:
        return await ctx.send("Aucune session en cours.")
    now = datetime.now(timezone.utc)
    rem = SESSION_END - now
    m, s = divmod(max(int(rem.total_seconds()), 0), 60)
    phase = 'travail' if SESSION_PHASE=='work' else 'pause'
    await ctx.send(f"Session {phase} : {m} min {s} sec restantes.")

@bot.command(name='stats', help='Voir statistiques d’utilisation')
@check_maintenance_mode()
async def stats(ctx):
    gid = ctx.guild.id
    db = TinyDB('leaderboard.json').table(str(gid))
    users = db.all()
    total = sum(u['minutes'] for u in users)
    count = len(users)
    embed = discord.Embed(
        title="📊 Stats Pomodoro",
        color=MsgColors.AQUA.value
    )
    embed.add_field(name="Utilisateurs", value=str(count), inline=False)
    embed.add_field(name="Temps total (min)", value=str(total), inline=False)
    await ctx.send(embed=embed)

@bot.command(name='help', help='Affiche la liste des commandes')
async def help_cmd(ctx):
    e = discord.Embed(title="🛠️ Commandes Pomodoro", color=MsgColors.PURPLE.value)
    e.add_field(
        name="Étudiant",
        value=(
            f"`{prefix}join` – rejoindre\n"
            f"`{prefix}leave` – quitter\n"
            f"`{prefix}time` – temps restant\n"
            f"`{prefix}stats` – vos stats\n"
            f"`{prefix}help` – ce message"
        ), inline=False
    )
    e.add_field(
        name="Admin",
        value=(
            f"`{prefix}leaderboard` – top 10\n"
            f"`{prefix}clear_stats` – vider stats\n"
            f"`{prefix}set_channel` – définir canal\n"
            f"`{prefix}set_role` – définir rôle\n"
            f"`{prefix}maintenance` – mode maint."
        ), inline=False
    )
    await ctx.send(embed=e)

# — POMODORO LOOP (inchangé) —
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    if not CHAN_ID:
        return
    channel = bot.get_channel(CHAN_ID)
    if not channel:
        return

    # Démarrer travail
    SESSION_ACTIVE = True
    SESSION_PHASE = 'work'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=WORK)
    mention = await get_role_mention(channel.guild)
    await channel.send(f"Début travail ({WORK} min) ! {mention}")
    await asyncio.sleep(WORK*60)

    # Démarrer pause
    SESSION_PHASE = 'break'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=BREAK)
    mention = await get_role_mention(channel.guild)
    await channel.send(f"Début pause ({BREAK} min) ! {mention}")
    await asyncio.sleep(BREAK*60)

    # En fin de session, on laisse aux users le soin de leave manuellement
    SESSION_ACTIVE = False

# — MAIN —
if __name__ == '__main__':
    keep_alive()
    bot.run(BOT_TOKEN)
