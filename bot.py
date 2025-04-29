import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from tinydb import TinyDB
from database import ajouter_temps, classement_top10, add_participant, remove_participant, get_all_participants
from keep_alive import keep_alive
import messages

# -------------------- CONFIGURATION & GLOBALS --------------------
config = configparser.ConfigParser()
config.read('settings.ini')

# Méthode A (50–10) et B (25–5)
WORK_TIME_A  = config['CURRENT_SETTINGS'].getint('work_time_A', fallback=50)
BREAK_TIME_A = config['CURRENT_SETTINGS'].getint('break_time_A', fallback=10)
POMO_ROLE_A  = config['CURRENT_SETTINGS'].get('pomodoro_role_A', fallback='50-10')
WORK_TIME_B  = config['CURRENT_SETTINGS'].getint('work_time_B', fallback=25)
BREAK_TIME_B = config['CURRENT_SETTINGS'].getint('break_time_B', fallback=5)
POMO_ROLE_B  = config['CURRENT_SETTINGS'].get('pomodoro_role_B', fallback='25-5')

# Canal de publication
POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)

# Préfixe et Intents
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
    # Charger les participants persistés
    for guild in bot.guilds:
        for uid, mode in get_all_participants(guild.id):
            if mode == 'A': PARTICIPANTS_A.add(uid)
            if mode == 'B': PARTICIPANTS_B.add(uid)
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()


@bot.event
async def on_command_error(ctx, error):
    # Erreur dispatch
    if isinstance(error, commands.CommandNotFound): key='command_not_found'
    elif isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance.": key='maintenance_active'
    elif isinstance(error, commands.MissingRequiredArgument): key='missing_argument'
    elif isinstance(error, commands.CheckFailure): key='permission_denied'
    else: key='unexpected_error'

    spec = messages.ERRORS[key]
    e = discord.Embed(color=spec['color'])
    e.title = spec['title']
    if key=='unexpected_error':
        e.description = spec['description_template'].format(error=error)
    else:
        e.description = spec['description']
    await ctx.send(embed=e)

# -------------------- COMMANDES ÉTUDIANT --------------------
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    if ctx.author.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return
    PARTICIPANTS_A.add(ctx.author.id)
    add_participant(ctx.author.id, ctx.guild.id, 'A')
    role=await ensure_role(ctx.guild,POMO_ROLE_A)
    await ctx.author.add_roles(role)
    tpl=messages.JOIN['A']
    e=discord.Embed(color=tpl['color'])
    e.description=tpl['description_template'].format(user_mention=ctx.author.mention)
    await ctx.send(embed=e)


@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    if ctx.author.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return
    PARTICIPANTS_B.add(ctx.author.id)
    add_participant(ctx.author.id, ctx.guild.id, 'B')
    role=await ensure_role(ctx.guild,POMO_ROLE_B)
    await ctx.author.add_roles(role)
    tpl=messages.JOIN['B']
    e=discord.Embed(color=tpl['color'])
    e.description=tpl['description_template'].format(user_mention=ctx.author.mention)
    await ctx.send(embed=e)


@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    join_ts,mode=remove_participant(ctx.author.id,ctx.guild.id)
    if join_ts is None:
        return
    secs=int(datetime.now(timezone.utc).timestamp()-join_ts)
    mins=max(secs//60,1)
    ajouter_temps(ctx.author.id,ctx.guild.id,mins)
    if mode=='A':
        PARTICIPANTS_A.discard(ctx.author.id)
        role=discord.utils.get(ctx.guild.roles,name=POMO_ROLE_A)
    else:
        PARTICIPANTS_B.discard(ctx.author.id)
        role=discord.utils.get(ctx.guild.roles,name=POMO_ROLE_B)
    if role: await ctx.author.remove_roles(role)
    tpl=messages.LEAVE
    e=discord.Embed(color=tpl['color'])
    e.description=tpl['description_template'].format(user_mention=ctx.author.mention,minutes=mins)
    await ctx.send(embed=e)


@bot.command(name='time', help='Temps restant session')
@check_maintenance()
async def time_left(ctx):
    if not SESSION_ACTIVE:
        e=discord.Embed(color=messages.TIME_LEFT['color'])
        e.description="Aucune session en cours."
        return await ctx.send(embed=e)
    rem=(SESSION_END-datetime.now(timezone.utc)).total_seconds()
    m,s=divmod(max(int(rem),0),60)
    phase=SESSION_PHASE
    next_phase='pause' if phase=='work' else 'travail'
    spec=messages.TIME_LEFT
    e=discord.Embed(title=spec['title_template'].format(phase=phase),color=spec['color'])
    e.description=spec['description_template'].format(next_phase=next_phase,minutes=m,seconds=s)
    await ctx.send(embed=e)

# -------------------- COMMANDE STATUS --------------------
@bot.command(name='status', help='Afficher latence et état du bot')
async def status(ctx):
    latency=round(bot.latency*1000)
    now_utc=datetime.now(timezone.utc)
    local=now_utc.astimezone(ZoneInfo('Europe/Zurich')).strftime("%Y-%m-%d %H:%M:%S")
    sess=(f"{SESSION_PHASE} dans { (SESSION_END-now_utc).seconds//60 } min" if SESSION_ACTIVE else "aucune session active")
    spec=messages.STATUS
    e=discord.Embed(title=spec['title'],color=spec['color'])
    for f in spec['fields']:
        val=f['value_template'].format(**{
            'latency':latency,'local_time':local,'session_status':sess
        })
        e.add_field(name=f['name'],value=val,inline=f['inline'])
    await ctx.send(embed=e)

# -------------------- STATS & LEADERBOARD --------------------
@bot.command(name='stats', help='Vos stats')
@check_maintenance()
async def stats(ctx):
    db=TinyDB('leaderboard.json').table(str(ctx.guild.id)).all()
    total=sum(r['minutes'] for r in db)
    count=len(db)
    avg=(total/count if count else 0)
    spec=messages.STATS
    e=discord.Embed(title=spec['title'],color=spec['color'])
    for f in spec['fields']:
        val=f['value_template'].format(**{
            'unique_users':count,
            'total_minutes':total,
            'average_minutes':avg
        })
        e.add_field(name=f['name'],value=val,inline=f['inline'])
    await ctx.send(embed=e)

@bot.command(name='leaderboard', help='Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top=classement_top10(ctx.guild.id)[:5]
    spec=messages.LEADERBOARD
    e=discord.Embed(title=spec['title'],color=spec['color'])
    for i,(uid,m) in enumerate(top,1):
        user=await bot.fetch_user(uid)
        e.add_field(
            name=spec['entry_template']['name_template'].format(rank=i,username=user.name),
            value=spec['entry_template']['value_template'].format(minutes=m),
            inline=False
        )
    await ctx.send(embed=e)

# -------------------- ADMIN --------------------
@bot.command(name='maintenance', help='Mode maintenance on/off')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE=not MAINTENANCE_MODE
    state="activée" if MAINTENANCE_MODE else "désactivée"
    spec=messages.MAINT_TOGGLE
    e=discord.Embed(title=spec['title'],color=spec['color'])
    e.description=spec['description_template'].format(state=state)
    await ctx.send(embed=e)

@bot.command(name='set_channel', help='Choisir canal (admin)')
@is_admin()
async def set_channel(ctx,channel:discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id']=str(channel.id)
    with open('settings.ini','w') as f:config.write(f)
    global POMODORO_CHANNEL_ID; POMODORO_CHANNEL_ID=channel.id
    spec=messages.SET_CHANNEL
    e=discord.Embed(color=spec['color'])
    e.description=spec['description_template'].format(channel_mention=channel.mention)
    await ctx.send(embed=e)

@bot.command(name='set_role_A', help='Définir rôle A (admin)')
@is_admin()
async def set_role_A(ctx,role:discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A']=role.name
    with open('settings.ini','w') as f:config.write(f)
    global POMO_ROLE_A; POMO_ROLE_A=role.name
    spec=messages.SET_ROLE_A
    e=discord.Embed(color=spec['color'])
    e.description=spec['description_template'].format(role_mention=role.mention)
    await ctx.send(embed=e)

@bot.command(name='set_role_B', help='Définir rôle B (admin)')
@is_admin()
async def set_role_B(ctx,role:discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B']=role.name
    with open('settings.ini','w') as f:config.write(f)
    global POMO_ROLE_B; POMO_ROLE_B=role.name
    spec=messages.SET_ROLE_B
    e=discord.Embed(color=spec['color'])
    e.description=spec['description_template'].format(role_mention=role.mention)
    await ctx.send(embed=e)

@bot.command(name='clear_stats', help='Réinitialiser toutes les stats')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    spec=messages.CLEAR_STATS
    e=discord.Embed(color=spec['color'])
    e.description=spec['description_template']
    await ctx.send(embed=e)

@bot.command(name='help', help='Affiche ce message')
async def help_cmd(ctx):
    spec=messages.HELP
    e=discord.Embed(title=spec['title'],color=spec['color'])
    for f in spec['fields']:
        e.add_field(name=f['name'],value=f['value'],inline=f['inline'])
    await ctx.send(embed=e)

# -------------------- BOUCLE POMODORO --------------------
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    channel=bot.get_channel(POMODORO_CHANNEL_ID)
    if not channel or not (PARTICIPANTS_A or PARTICIPANTS_B): return

    # méthode A
    if PARTICIPANTS_A:
        SESSION_ACTIVE,SESSION_PHASE = True,'work'
        SESSION_END = datetime.now(timezone.utc)+timedelta(minutes=WORK_TIME_A)
        role_mention=(await ensure_role(channel.guild,POMO_ROLE_A)).mention
        tpl=messages.LOOP
        await channel.send(tpl['start_template'].format(mode='A',duration=WORK_TIME_A,role_mention=role_mention))
        await asyncio.sleep(WORK_TIME_A*60)
        SESSION_PHASE='break'
        SESSION_END = datetime.now(timezone.utc)+timedelta(minutes=BREAK_TIME_A)
        await channel.send(tpl['pause_template'].format(mode='A',duration=BREAK_TIME_A,role_mention=role_mention))
        await asyncio.sleep(BREAK_TIME_A*60)
        for uid in PARTICIPANTS_A: ajouter_temps(uid,channel.guild.id,WORK_TIME_A)
        SESSION_ACTIVE=False

    # méthode B
    if PARTICIPANTS_B:
        SESSION_ACTIVE,SESSION_PHASE = True,'work'
        SESSION_END = datetime.now(timezone.utc)+timedelta(minutes=WORK_TIME_B)
        role_mention=(await ensure_role(channel.guild,POMO_ROLE_B)).mention
        tpl=messages.LOOP
        await channel.send(tpl['start_template'].format(mode='B',duration=WORK_TIME_B,role_mention=role_mention))
        await asyncio.sleep(WORK_TIME_B*60)
        SESSION_PHASE='break'
        SESSION_END = datetime.now(timezone.utc)+timedelta(minutes=BREAK_TIME_B)
        await channel.send(tpl['pause_template'].format(mode='B',duration=BREAK_TIME_B,role_mention=role_mention))
        await asyncio.sleep(BREAK_TIME_B*60)
        for uid in PARTICIPANTS_B: ajouter_temps(uid,channel.guild.id,WORK_TIME_B)
        SESSION_ACTIVE=False

# -------------------- MAIN --------------------
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
