import os
import discord
from discord.ext import commands
import configparser
import asyncio
from enum import Enum
from database import ajouter_temps, recuperer_temps, classement_top10
from keep_alive import keep_alive
import logging
from tinydb import TinyDB
from datetime import datetime, timezone, timedelta

# -- CONFIGURATION & GLOBALS ------------------------------------------
config = configparser.ConfigParser()
config.read('settings.ini')

prefix               = config['CURRENT_SETTINGS'].get('prefix', '*')
WORK_TIME_A          = int(config['CURRENT_SETTINGS'].get('work_time', 50))
BREAK_TIME_A         = int(config['CURRENT_SETTINGS'].get('break_time', 10))
WORK_TIME_B          = 25
BREAK_TIME_B         = 5
POMODORO_CHANNEL_ID  = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
POMODORO_ROLE_A      = config['CURRENT_SETTINGS'].get('pomodoro_role', '50-10')
POMODORO_ROLE_B      = '25-5'
discord_token        = os.getenv('DISCORD_TOKEN')

SESSION_ACTIVE       = False
SESSION_PHASE        = None     # 'work' ou 'break'
SESSION_END          = None
participants         = {}       # user_id -> join_timestamp

# -- BOT SETUP --------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=prefix,
    help_command=None,
    intents=intents,
    case_insensitive=True
)

# -- LOGGING ----------------------------------------------------------
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.INFO)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

# -- EMBED COLORS -----------------------------------------------------
class C(Enum):
    AQUA   = 0x33c6bb
    PURPLE = 0x6040b1
    RED    = 0xEA3546
    YELLOW = 0xFFD966

# -- UTILITAIRES ------------------------------------------------------
def is_admin():
    async def pred(ctx): return ctx.author.guild_permissions.administrator
    return commands.check(pred)

async def get_or_create_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name)
        logger.info(f"Rôle '{name}' créé dans le serveur '{guild.name}'")
    return role

# -- ÉVÉNEMENTS -------------------------------------------------------
@bot.event
async def on_ready():
    logger.info(f"{bot.user} connecté.")
    keep_alive()

@bot.event
async def on_message(message):
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    embed = discord.Embed(color=C.RED.value)
    if isinstance(error, commands.CommandNotFound):
        embed.title = "❓ Commande inconnue"
        embed.description = f"Tapez `{prefix}help` pour la liste des commandes."
    elif isinstance(error, commands.MissingRequiredArgument):
        embed.title = "❗ Argument manquant"
        embed.description = "Vérifiez la syntaxe de la commande."
    elif isinstance(error, commands.CheckFailure):
        embed.title = "🚫 Permission refusée"
        embed.description = "Vous n'avez pas les permissions requises."
    else:
        embed.title = "❌ Erreur inattendue"
        embed.description = str(error)
        logger.error(error)
    await ctx.send(embed=embed)

# -- COMMANDES ÉTUDIANT ------------------------------------------------
@bot.command(name='joina', help='Rejoindre mode A (50-10)')
async def joina(ctx):
    uid = ctx.author.id
    if uid in participants:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit en mode A ou B.",
            color=C.YELLOW.value
        ))
    participants[uid] = datetime.now(timezone.utc)
    role = await get_or_create_role(ctx.guild, POMODORO_ROLE_A)
    await ctx.author.add_roles(role)
    # démarrer session si non active
    if not SESSION_ACTIVE:
        asyncio.create_task(run_session(WORK_TIME_A, BREAK_TIME_A))
    await ctx.send(embed=discord.Embed(
        description=f"{ctx.author.mention} a rejoint (mode A).",
        color=C.AQUA.value
    ))

@bot.command(name='joinb', help='Rejoindre mode B (25-5)')
async def joinb(ctx):
    uid = ctx.author.id
    if uid in participants:
        return await ctx.send(embed=discord.Embed(
            description="Vous êtes déjà inscrit en mode A ou B.",
            color=C.YELLOW.value
        ))
    participants[uid] = datetime.now(timezone.utc)
    role = await get_or_create_role(ctx.guild, POMODORO_ROLE_B)
    await ctx.author.add_roles(role)
    if not SESSION_ACTIVE:
        asyncio.create_task(run_session(WORK_TIME_B, BREAK_TIME_B))
    await ctx.send(embed=discord.Embed(
        description=f"{ctx.author.mention} a rejoint (mode B).",
        color=C.AQUA.value
    ))

@bot.command(name='leave', help='Quitter le Pomodoro')
async def leave(ctx):
    uid = ctx.author.id
    if uid not in participants:
        return await ctx.send(embed=discord.Embed(
            description="Vous n'étiez pas inscrit.",
            color=C.YELLOW.value
        ))
    start = participants.pop(uid)
    elapsed = int((datetime.now(timezone.utc) - start).total_seconds() // 60)
    ajouter_temps(uid, ctx.guild.id, elapsed)
    # retirer rôles A et B
    for rn in (POMODORO_ROLE_A, POMODORO_ROLE_B):
        r = discord.utils.get(ctx.guild.roles, name=rn)
        if r: await ctx.author.remove_roles(r)
    await ctx.send(embed=discord.Embed(
        description=f"{ctx.author.mention} a quitté, +{elapsed} min ajoutées.",
        color=C.AQUA.value
    ))

@bot.command(name='time', help='Temps restant de la session')
async def time_left(ctx):
    if not SESSION_ACTIVE or SESSION_PHASE is None:
        return await ctx.send(embed=discord.Embed(
            description="Aucune session en cours.",
            color=C.YELLOW.value
        ))
    now = datetime.now(timezone.utc)
    remaining = SESSION_END - now
    secs = max(int(remaining.total_seconds()),0)
    mins, secs = divmod(secs, 60)
    phase = 'travail' if SESSION_PHASE == 'work' else 'pause'
    nextp = 'pause' if SESSION_PHASE=='work' else 'travail'
    await ctx.send(embed=discord.Embed(
        title=f"⏱️ Session {phase}",
        description=f"La {nextp} commence dans **{mins}** min et **{secs}** sec.",
        color=C.AQUA.value
    ))

@bot.command(name='ping', help='Vérifier la latence')
async def ping(ctx):
    await ctx.send(embed=discord.Embed(
        title="🏓 Pong !",
        description=f"Latence : **{round(bot.latency*1000)}** ms",
        color=C.AQUA.value
    ))

# -- COMMANDES ADMIN ---------------------------------------------------
@bot.command(name='maintenance', help='Activer/désactiver maintenance')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = 'activée' if MAINTENANCE_MODE else 'désactivée'
    await ctx.send(embed=discord.Embed(
        title="🔧 Mode Maintenance",
        description=f"Mode maintenance {state}.",
        color=C.YELLOW.value
    ))

@bot.command(name='set_channel', help='Définir canal Pomodoro')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini','w') as f: config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    await ctx.send(embed=discord.Embed(
        description=f"Canal défini sur {channel.mention}.",
        color=C.AQUA.value
    ))

@bot.command(name='set_role', help='Définir rôle Pomodoro')
@is_admin()
async def set_role(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global POMODORO_ROLE_A
    POMODORO_ROLE_A = role.name
    await ctx.send(embed=discord.Embed(
        description=f"Rôle Pomodoro défini sur {role.name}.",
        color=C.AQUA.value
    ))

@bot.command(name='stats', help='Voir statistiques')
@is_admin()
async def stats(ctx):
    db = TinyDB('leaderboard.json')
    t = db.table(str(ctx.guild.id))
    users = t.all()
    total = sum(u['minutes'] for u in users)
    count = len(users)
    avg = total/count if count else 0
    embed = discord.Embed(title="📊 Stats Pomodoro", color=C.AQUA.value)
    embed.add_field("Utilisateurs uniques",count,False)
    embed.add_field("Temps total (min)",total,False)
    embed.add_field("Moyenne par user",f"{avg:.1f}",False)
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', help='Top 10 Pomodoro')
@is_admin()
async def leaderboard(ctx):
    top10 = classement_top10(ctx.guild.id)
    embed = discord.Embed(title="🏆 Leaderboard",color=C.PURPLE.value)
    if not top10:
        embed.description="Aucun utilisateur."
    else:
        for i,(uid,mins) in enumerate(top10,1):
            user = await bot.fetch_user(uid)
            embed.add_field(f"#{i} {user.name}",f"{mins} min",False)
    await ctx.send(embed=embed)

@bot.command(name='clear_stats', help='Réinitialiser stats')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    await ctx.send(embed=discord.Embed(
        description="Statistiques réinitialisées.",
        color=C.YELLOW.value
    ))

@bot.command(name='help', help='Afficher l’aide')
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🛠️ Commandes Pomodoro",
        color=C.PURPLE.value
    )
    embed.add_field("Étudiant",
        "`joina`, `joinb`, `leave`, `time`, `ping`, `help`",False)
    embed.add_field("Admin",
        "`maintenance`, `set_channel`, `set_role`, `stats`, `leaderboard`, `clear_stats`",False)
    await ctx.send(embed=embed)

# -- SESSION COROUTINE ------------------------------------------------
async def run_session(work_time:int, break_time:int):
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    if SESSION_ACTIVE or not participants:
        return
    SESSION_ACTIVE = True

    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    mentionA = await get_or_create_role(channel.guild, POMODORO_ROLE_A)
    mentionB = await get_or_create_role(channel.guild, POMODORO_ROLE_B)

    # TRAVAIL
    SESSION_PHASE = 'work'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=work_time)
    await channel.send(embed=discord.Embed(
        description=f"Début travail ({work_time} min) ! {mentionA}",
        color=C.AQUA.value
    ))
    await asyncio.sleep(work_time*60)

    # PAUSE
    SESSION_PHASE = 'break'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=break_time)
    await channel.send(embed=discord.Embed(
        description=f"Début pause ({break_time} min) ! {mentionA}",
        color=C.AQUA.value
    ))
    await asyncio.sleep(break_time*60)

    # FIN DE SESSION → enregistrer temps
    now = datetime.now(timezone.utc)
    for uid,start in list(participants.items()):
        elapsed = int((now - start).total_seconds()//60)
        ajouter_temps(uid, channel.guild.id, elapsed)

    SESSION_ACTIVE = False

# -- MAIN -------------------------------------------------------------
if __name__ == '__main__':
    bot.run(discord_token)
