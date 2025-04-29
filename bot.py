import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
import logging
from enum import Enum
from datetime import datetime, timezone, timedelta
from tinydb import TinyDB, Query
from keep_alive import keep_alive

# -- CONFIG & GLOBALS --
config = configparser.ConfigParser()
config.read('settings.ini')

WORK_TIME_A    = int(config['CURRENT_SETTINGS']['work_time_A'])    # ex: 50
BREAK_TIME_A   = int(config['CURRENT_SETTINGS']['break_time_A'])   # ex: 10
WORK_TIME_B    = int(config['CURRENT_SETTINGS']['work_time_B'])    # ex: 25
BREAK_TIME_B   = int(config['CURRENT_SETTINGS']['break_time_B'])   # ex: 5
POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)

# noms par défaut, peuvent être modifiés via commandes
ROLE_NAME_A = config['CURRENT_SETTINGS'].get('pomodoro_role_A', '50-10')
ROLE_NAME_B = config['CURRENT_SETTINGS'].get('pomodoro_role_B', '25-5')

prefix   = config['CURRENT_SETTINGS'].get('prefix', '*')
discord_token = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=prefix,
                   help_command=None,
                   intents=intents,
                   case_insensitive=True)

# Logger
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S'))
logger.addHandler(fh)

class MsgColors(Enum):
    AQUA   = 0x33c6bb
    YELLOW = 0xFFD966
    RED    = 0xEA3546
    PURPLE = 0x6040b1

# Stockage temporaire des sessions en cours { user_id: { mode:'A'|'B', join:datetime } }
sessions: dict[int, dict] = {}

# -------------------- UTILS --------------------
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name)
        logger.info(f"Rôle '{name}' créé dans {guild.name}")
    return role

def db_table(guild_id: int):
    db = TinyDB('leaderboard.json')
    return db.table(str(guild_id))

# -------------------- EVENTS --------------------
@bot.event
async def on_ready():
    logger.info(f'{bot.user} connecté')
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    embed = discord.Embed(color=MsgColors.RED.value)
    if isinstance(error, commands.CommandNotFound):
        embed.title = "Commande inconnue"
        embed.description = f"Tapez `{prefix}help` pour la liste."
    elif isinstance(error, commands.MissingRequiredArgument):
        embed.title = "Argument manquant"
        embed.description = "Vérifiez la syntaxe."
    elif isinstance(error, commands.CheckFailure):
        embed.title = "Permission refusée"
        embed.description = "Vous n'avez pas les droits."
    else:
        embed.title = "Erreur inattendue"
        embed.description = str(error)
        logger.error(f"Erreur: {error}")
    await ctx.send(embed=embed)

# -------------------- COMMANDES ÉTUDIANT --------------------
@bot.command(name='joina', help='Rejoindre mode A (50-10)')
async def joina(ctx):
    user = ctx.author
    if user.id in sessions:
        embed = discord.Embed(
            description=f"{user.mention} déjà en session.",
            color=MsgColors.YELLOW.value
        )
    else:
        role = await ensure_role(ctx.guild, ROLE_NAME_A)
        await user.add_roles(role)
        sessions[user.id] = {'mode':'A','join':datetime.now(timezone.utc)}
        embed = discord.Embed(
            description=f"{user.mention} a rejoint le mode A.",
            color=MsgColors.AQUA.value
        )
    await ctx.send(embed=embed)

@bot.command(name='joinb', help='Rejoindre mode B (25-5)')
async def joinb(ctx):
    user = ctx.author
    if user.id in sessions:
        embed = discord.Embed(
            description=f"{user.mention} déjà en session.",
            color=MsgColors.YELLOW.value
        )
    else:
        role = await ensure_role(ctx.guild, ROLE_NAME_B)
        await user.add_roles(role)
        sessions[user.id] = {'mode':'B','join':datetime.now(timezone.utc)}
        embed = discord.Embed(
            description=f"{user.mention} a rejoint le mode B.",
            color=MsgColors.AQUA.value
        )
    await ctx.send(embed=embed)

@bot.command(name='leave', help='Quitter la session active')
async def leave(ctx):
    user = ctx.author
    info = sessions.pop(user.id, None)
    if not info:
        embed = discord.Embed(
            description=f"{user.mention} n’était pas en session.",
            color=MsgColors.YELLOW.value
        )
    else:
        now = datetime.now(timezone.utc)
        delta = now - info['join']
        minutes = int(delta.total_seconds() // 60)
        # met à jour TinyDB
        table = db_table(ctx.guild.id)
        Q = Query()
        rec = table.get(Q.user_id == user.id)
        if not rec:
            table.insert({'user_id':user.id,
                          'minutes_A':0,'minutes_B':0})
            rec = table.get(Q.user_id == user.id)
        field = 'minutes_A' if info['mode']=='A' else 'minutes_B'
        table.update({field: rec[field] + minutes}, Q.user_id==user.id)
        # on retire le rôle
        role_name = ROLE_NAME_A if info['mode']=='A' else ROLE_NAME_B
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role: await user.remove_roles(role)
        embed = discord.Embed(
            description=f"{user.mention} a quitté. +{minutes} min mode {info['mode']}.",
            color=MsgColors.AQUA.value
        )
    await ctx.send(embed=embed)

@bot.command(name='time', help='Temps restant jusqu’à la phase suivante')
async def time_left(ctx):
    # On prend la session la plus récente si plusieurs (mais on n’autorise qu’une à la fois)
    user = ctx.author
    info = sessions.get(user.id)
    if not info:
        embed = discord.Embed(
            description="Aucune session en cours.",
            color=MsgColors.YELLOW.value
        )
        return await ctx.send(embed=embed)
    mode = info['mode']
    work = WORK_TIME_A if mode=='A' else WORK_TIME_B
    brk  = BREAK_TIME_A if mode=='A' else BREAK_TIME_B
    start = info['join']
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    cycle = work*60 + brk*60
    pos = elapsed % cycle
    if pos < work*60:
        remaining = work*60 - pos
        phase = 'travail'
        nextp = 'pause'
    else:
        remaining = cycle - pos
        phase = 'pause'
        nextp = 'travail'
    mins, secs = divmod(int(remaining),60)
    embed = discord.Embed(
        title=f"Session mode {mode} – {phase}",
        description=f"La {nextp} dans **{mins}** min **{secs}** sec.",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=embed)

@bot.command(name='stats', help='Vos statistiques Pomodoro')
async def stats(ctx):
    table = db_table(ctx.guild.id)
    rec = table.get(Query().user_id==ctx.author.id)
    a = rec['minutes_A'] if rec else 0
    b = rec['minutes_B'] if rec else 0
    tot = a + b
    embed = discord.Embed(title="Stats Pomodoro", color=MsgColors.AQUA.value)
    embed.add_field(name="Mode A",      value=f"{a} min", inline=True)
    embed.add_field(name="Mode B",      value=f"{b} min", inline=True)
    embed.add_field(name="Total",       value=f"{tot} min", inline=True)
    await ctx.send(embed=embed)

# -------------------- COMMANDES ADMIN --------------------
@bot.command(name='leaderboard', help='Top 10 tous modes confondus')
@is_admin()
async def leaderboard(ctx):
    table = db_table(ctx.guild.id)
    users = table.all()
    # calc total
    ranking = sorted(users,
                     key=lambda r: r['minutes_A']+r['minutes_B'],
                     reverse=True)[:10]
    embed = discord.Embed(title="Leaderboard Pomodoro", color=MsgColors.PURPLE.value)
    if not ranking:
        embed.description = "Aucun utilisateur."
    else:
        for i, r in enumerate(ranking, start=1):
            user = await bot.fetch_user(r['user_id'])
            tot = r['minutes_A']+r['minutes_B']
            embed.add_field(name=f"#{i} {user.name}", value=f"{tot} min", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='set_channel', help='Définir #salon Pomodoro')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini','w') as f: config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    embed = discord.Embed(
        description=f"Canal Pomodoro → {channel.mention}",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=embed)

@bot.command(name='set_role_a', help='Définir @role mode A')
@is_admin()
async def set_role_a(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global ROLE_NAME_A
    ROLE_NAME_A = role.name
    embed = discord.Embed(
        description=f"Rôle mode A → {role.mention}",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=embed)

@bot.command(name='set_role_b', help='Définir @role mode B')
@is_admin()
async def set_role_b(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global ROLE_NAME_B
    ROLE_NAME_B = role.name
    embed = discord.Embed(
        description=f"Rôle mode B → {role.mention}",
        color=MsgColors.AQUA.value
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
    embed = discord.Embed(title="Commandes Pomodoro", color=MsgColors.PURPLE.value)
    embed.add_field(
        name="Étudiant",
        value=(
            "`joina` – rejoindre mode A\n"
            "`joinb` – rejoindre mode B\n"
            "`leave` – quitter session\n"
            "`time` – temps restant\n"
            "`stats` – vos stats\n"
            "`help` – ce message"
        ),
        inline=False
    )
    embed.add_field(
        name="Administrateur",
        value=(
            "`leaderboard` – top 10 total\n"
            "`set_channel #salon`\n"
            "`set_role_a @role`\n"
            "`set_role_b @role`\n"
            "`clear_stats` – vider stats"
        ),
        inline=False
    )
    await ctx.send(embed=embed)

# -------------------- BOUCLE (inutile désormais) --------------------
@tasks.loop(minutes=1)
async def pomodoro_loop():
    # on n’envoie plus automatiquement de sessions globales
    pass

# -------------------- MAIN --------------------
if __name__ == '__main__':
    keep_alive()
    bot.run(discord_token)
