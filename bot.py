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

PARTICIPANTS = []

# Charger config
config = configparser.ConfigParser()
config.read('settings.ini')
WORK_TIME = int(config['CURRENT_SETTINGS']['work_time'])
BREAK_TIME = int(config['CURRENT_SETTINGS']['break_time'])
POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
POMODORO_ROLE_NAME   = config['CURRENT_SETTINGS'].get('pomodoro_role', '50-10')
prefix = config['CURRENT_SETTINGS'].get('prefix', '*')

# Bot setup
discord_token = os.getenv('DISCORD_TOKEN')
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=prefix,
    help_command=None,
    intents=intents,
    case_insensitive=True
)

# Logging
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

# Couleurs embeds
class MsgColors(Enum):
    AQUA   = 0x33c6bb
    YELLOW = 0xFFD966
    RED    = 0xEA3546
    PURPLE = 0x6040b1

# -------------- UTILITAIRES --------------
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

async def get_role_mention(guild: discord.Guild) -> str:
    role = discord.utils.get(guild.roles, name=POMODORO_ROLE_NAME)
    if role is None:
        role = await guild.create_role(name=POMODORO_ROLE_NAME)
        logger.info(f"Rôle '{POMODORO_ROLE_NAME}' créé dans {guild.name}")
    return role.mention

# -------------- ÉVÉNEMENTS --------------
@bot.event
async def on_ready():
    logger.info(f'{bot.user} connecté.')
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_message(message):
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    embed = discord.Embed(color=MsgColors.RED.value)
    if isinstance(error, commands.CommandNotFound):
        embed.title = "❓ Commande inconnue"
        embed.description = f"Tapez `{prefix}help` pour la liste des commandes."
    elif isinstance(error, commands.CommandError) and str(error) == "Bot en mode maintenance.":
        embed.title = "⚠️ Maintenance"
        embed.description = "Le bot est en maintenance."
    elif isinstance(error, commands.MissingRequiredArgument):
        embed.title = "❗ Argument manquant"
        embed.description = "Vérifiez la syntaxe de la commande."
    elif isinstance(error, commands.CheckFailure):
        embed.title = "🚫 Permission refusée"
        embed.description = "Vous n'avez pas la permission."
    else:
        embed.title = "❌ Erreur inattendue"
        embed.description = str(error)
        logger.error(f"Erreur : {error}")
    await ctx.send(embed=embed)

# -------------- COMMANDES --------------
@bot.command(name='maintenance', help='Activer/désactiver maintenance')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = 'activée' if MAINTENANCE_MODE else 'désactivée'
    embed = discord.Embed(
        title="🔧 Mode Maintenance",
        description=f"Mode maintenance {state}.",
        color=MsgColors.YELLOW.value
    )
    await ctx.send(embed=embed)

@bot.command(name='join', help='Rejoindre le Pomodoro (A ou B)')
@check_maintenance_mode()
async def join(ctx):
    user = ctx.author
    if user.id not in PARTICIPANTS:
        PARTICIPANTS.append(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMODORO_ROLE_NAME)
        await user.add_roles(role)
        embed = discord.Embed(
            description=f"{user.mention} a rejoint le Pomodoro.",
            color=MsgColors.AQUA.value
        )
    else:
        embed = discord.Embed(
            description=f"{user.mention} est déjà inscrit.",
            color=MsgColors.YELLOW.value
        )
    await ctx.send(embed=embed)

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance_mode()
async def leave(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS:
        PARTICIPANTS.remove(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMODORO_ROLE_NAME)
        if role:
            await user.remove_roles(role)
        minutes = int((WORK_TIME if SESSION_PHASE=='work' else BREAK_TIME))
        ajouter_temps(user.id, ctx.guild.id, minutes)
        embed = discord.Embed(
            description=f"{user.mention} a quitté. +{minutes} min ajoutées.",
            color=MsgColors.AQUA.value
        )
    else:
        embed = discord.Embed(
            description=f"{user.mention} n'était pas inscrit.",
            color=MsgColors.YELLOW.value
        )
    await ctx.send(embed=embed)

@bot.command(name='time', help='Temps restant de la session')
@check_maintenance_mode()
async def time_left(ctx):
    if not SESSION_ACTIVE or SESSION_PHASE is None:
        embed = discord.Embed(
            description="Aucune session en cours.",
            color=MsgColors.YELLOW.value
        )
        return await ctx.send(embed=embed)
    now = datetime.now(timezone.utc)
    rem = max(int((SESSION_END-now).total_seconds()), 0)
    m, s = divmod(rem, 60)
    phase = 'travail' if SESSION_PHASE=='work' else 'pause'
    nxt   = 'pause'   if SESSION_PHASE=='work' else 'travail'
    embed = discord.Embed(
        title=f"⏱️ Session {phase}",
        description=f"La {nxt} commence dans **{m}** min **{s}** sec.",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=embed)

@bot.command(name='ping', help='Latence du bot')
async def ping(ctx):
    embed = discord.Embed(
        title="🏓 Pong !",
        description=f"Latence : **{round(bot.latency*1000)}** ms",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=embed)

@bot.command(name='stats', help='Voir vos stats')
@check_maintenance_mode()
async def stats(ctx):
    db = TinyDB('leaderboard.json')
    table = db.table(str(ctx.guild.id))
    users = table.all()
    total = sum(u['minutes'] for u in users) if users else 0
    count = len(users)
    avg   = (total/count) if count else 0
    embed = discord.Embed(title="📊 Stats Pomodoro", color=MsgColors.AQUA.value)
    embed.add_field(name="Utilisateurs uniques", value=str(count), inline=False)
    embed.add_field(name="Temps total (min)",       value=str(total), inline=False)
    embed.add_field(name="Moyenne par utilisateur", value=f"{avg:.1f} min", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', help='Top 10 Pomodoro')
@check_maintenance_mode()
async def leaderboard(ctx):
    top10 = classement_top10(ctx.guild.id)
    embed = discord.Embed(title="🏆 Leaderboard Pomodoro", color=MsgColors.PURPLE.value)
    if not top10:
        embed.description = "Aucun utilisateur."
    else:
        for i, (uid, mins) in enumerate(top10, start=1):
            user = await bot.fetch_user(uid)
            embed.add_field(
                name=f"#{i} {user.name}",
                value=f"{mins} min",
                inline=False
            )
    await ctx.send(embed=embed)

@bot.command(name='clear_stats', help='Vider toutes les stats')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    embed = discord.Embed(
        description="Statistiques réinitialisées.",
        color=MsgColors.YELLOW.value
    )
    await ctx.send(embed=embed)

@bot.command(name='help', help='Affiche ce message')
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🛠️ Commandes Pomodoro",
        color=MsgColors.PURPLE.value
    )
    embed.add_field(
        name="Étudiant",
        value=(
            "`join`        – rejoindre\n"
            "`leave`       – quitter\n"
            "`time`        – temps restant\n"
            "`ping`        – latence bot\n"
            "`stats`       – vos stats\n"
            "`leaderboard` – top 10\n"
            "`help`        – ce message"
        ),
        inline=False
    )
    embed.add_field(
        name="Administrateur",
        value=(
            "`maintenance` – maintenance on/off\n"
            "`set_channel` – définir canal\n"
            "`set_role`    – définir rôle\n"
            "`clear_stats` – vider stats"
        ),
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(name='set_channel', help='Définir canal Pomodoro')
@is_admin()
async def set_channel_cmd(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    embed = discord.Embed(
        description=f"Canal défini sur {channel.mention}.",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=embed)

@bot.command(name='set_role', help='Définir rôle Pomodoro')
@is_admin()
async def set_role_cmd(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role'] = role.name
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMODORO_ROLE_NAME
    POMODORO_ROLE_NAME = role.name
    embed = discord.Embed(
        description=f"Rôle défini sur {role.mention}.",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=embed)

# -------------- BOUCLE POMODORO --------------
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    work = int(config['CURRENT_SETTINGS']['work_time'])
    brk  = int(config['CURRENT_SETTINGS']['break_time'])
    cid  = POMODORO_CHANNEL_ID or None
    channel = bot.get_channel(cid) if cid else None
    if not channel or not PARTICIPANTS:
        return

    SESSION_ACTIVE = True

    # Travail
    SESSION_PHASE = 'work'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=work)
    mention = await get_role_mention(channel.guild)
    await channel.send(f"Début travail ({work} min) ! {mention}")
    await asyncio.sleep(work * 60)

    # Pause
    SESSION_PHASE = 'break'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=brk)
    mention = await get_role_mention(channel.guild)
    await channel.send(f"Début pause ({brk} min) ! {mention}")
    await asyncio.sleep(brk * 60)

    # Sauvegarde temps
    for uid in PARTICIPANTS:
        ajouter_temps(uid, channel.guild.id, work)
    logger.info(f"Temps ajouté pour {PARTICIPANTS}")
    SESSION_ACTIVE = False

# -------------- MAIN --------------
if __name__ == '__main__':
    keep_alive()
    bot.run(discord_token)
