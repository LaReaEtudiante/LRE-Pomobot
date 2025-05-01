import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from tinydb import TinyDB
from database import (
    ajouter_temps,
    recuperer_temps,
    classement_top10,
    add_participant,
    remove_participant,
    get_all_participants
)
from keep_alive import keep_alive
import messages

# ─── CONFIG & GLOBALS ─────────────────────────────────────────────────────────
config = configparser.ConfigParser()
config.read('settings.ini')

WORK_TIME_A        = config['CURRENT_SETTINGS'].getint('work_time_A',   fallback=50)
BREAK_TIME_A       = config['CURRENT_SETTINGS'].getint('break_time_A',  fallback=10)
POMODORO_ROLE_A    = config['CURRENT_SETTINGS'].get('pomodoro_role_A', fallback='50-10')
WORK_TIME_B        = config['CURRENT_SETTINGS'].getint('work_time_B',   fallback=25)
BREAK_TIME_B       = config['CURRENT_SETTINGS'].getint('break_time_B',  fallback=5)
POMODORO_ROLE_B    = config['CURRENT_SETTINGS'].get('pomodoro_role_B', fallback='25-5')
POMODORO_CHANNEL_ID= config['CURRENT_SETTINGS'].getint('channel_id',    fallback=None)
PREFIX             = config['CURRENT_SETTINGS'].get('prefix',           '*')
MAINTENANCE_MODE   = False

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=PREFIX,
    help_command=None,
    intents=intents,
    case_insensitive=True
)

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# ─── STATE ─────────────────────────────────────────────────────────────────────
SESSION_ACTIVE = False
SESSION_PHASE  = None  # 'work' or 'break'
SESSION_END    = None
PARTICIPANTS_A = set()
PARTICIPANTS_B = set()

# ─── UTILS ─────────────────────────────────────────────────────────────────────
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

# ─── EVENTS ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global MAINTENANCE_MODE
    logger.info(f"{bot.user} connecté.")
    # Restaurer les participants persistés
    for guild in bot.guilds:
        for uid, mode in get_all_participants(guild.id):
            if mode == 'A':
                PARTICIPANTS_A.add(uid)
            else:
                PARTICIPANTS_B.add(uid)
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    # Choix de la clé dans messages.ERRORS
    key = (
        "command_not_found" if isinstance(error, commands.CommandNotFound) else
        "maintenance_active" if isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance." else
        "missing_argument" if isinstance(error, commands.MissingRequiredArgument) else
        "permission_denied" if isinstance(error, commands.CheckFailure) else
        "unexpected_error"
    )
    tpl = messages.ERRORS[key]
    embed = discord.Embed(
        title=tpl["title"],
        description=tpl["description_template"].format(prefix=PREFIX, error=str(error)),
        color=tpl["color"]
    )
    await ctx.send(embed=embed)

# ─── COMMANDES ÉTUDIANT ────────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        tpl = messages.JOIN["ALREADY"]
    else:
        PARTICIPANTS_A.add(user.id)
        add_participant(user.id, ctx.guild.id, 'A')
        tpl = messages.JOIN["A"]
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(user_mention=user.mention),
        color=tpl["color"]
    ))

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        tpl = messages.JOIN["ALREADY"]
    else:
        PARTICIPANTS_B.add(user.id)
        add_participant(user.id, ctx.guild.id, 'B')
        tpl = messages.JOIN["B"]
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(user_mention=user.mention),
        color=tpl["color"]
    ))

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        # Pas inscrit
        await ctx.send(embed=discord.Embed(
            description="⚠️ Vous n'étiez pas inscrit.",
            color=messages.MsgColors.YELLOW.value
        ))
        return

    # Calculer durée réelle
    now_ts = datetime.now(timezone.utc).timestamp()
    mins = max(int((now_ts - join_ts) // 60), 1)
    ajouter_temps(user.id, ctx.guild.id, mins)

    tpl = messages.LEAVE
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(
            user_mention=user.mention,
            minutes=mins
        ),
        color=tpl["color"]
    ))

# ─── TEMPS RESTANT ─────────────────────────────────────────────────────────────
@bot.command(name='time', help='Temps restant de la session en cours')
@check_maintenance()
async def time_left(ctx):
    if not SESSION_ACTIVE or SESSION_PHASE is None:
        await ctx.send("ℹ️ Aucune session en cours.")
        return

    now = datetime.now(timezone.utc)
    rem = max(int((SESSION_END - now).total_seconds()), 0)
    m, s = divmod(rem, 60)
    phase = SESSION_PHASE
    next_phase = 'pause' if phase == 'work' else 'travail'
    tpl = messages.TIME_LEFT
    await ctx.send(embed=discord.Embed(
        title=tpl["title_template"].format(phase=phase),
        description=tpl["description_template"].format(
            next_phase=next_phase,
            minutes=m,
            seconds=s
        ),
        color=tpl["color"]
    ))

# ─── STATUS ───────────────────────────────────────────────────────────────────
@bot.command(name='status', help='Afficher latence et état du bot')
async def status(ctx):
    latency = round(bot.latency * 1000)
    now_utc = datetime.now(timezone.utc)
    local = now_utc.astimezone(ZoneInfo('Europe/Zurich'))
    # Statut session
    if SESSION_ACTIVE and SESSION_END:
        rem = max(int((SESSION_END - now_utc).total_seconds()), 0)
        m, s = divmod(rem, 60)
        sess = f"{SESSION_PHASE} dans {m} min {s} sec"
        ends_at = (SESSION_END.astimezone(ZoneInfo('Europe/Zurich'))
                   .strftime("%H:%M:%S"))
    else:
        sess = "aucune"
        ends_at = "—"
    # Comptages
    count_A = len(PARTICIPANTS_A)
    count_B = len(PARTICIPANTS_B)

    embed = discord.Embed(
        title=messages.STATUS["title"],
        color=messages.STATUS["color"]
    )
    for field in messages.STATUS["fields"]:
        value = field["value_template"].format(
            latency=latency,
            local_time=local.strftime("%Y-%m-%d %H:%M:%S"),
            session_status=sess,
            ends_at=ends_at,
            count_A=count_A,
            count_B=count_B
        )
        embed.add_field(
            name=field["name"],
            value=value,
            inline=field["inline"]
        )
    await ctx.send(embed=embed)

# ─── STATS ET LEADERBOARD ─────────────────────────────────────────────────────
@bot.command(name='stats', help='Voir statistiques d’utilisation')
@check_maintenance()
async def stats(ctx):
    table = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    all_   = table.all()
    unique = len(all_)
    total  = sum(u['minutes'] for u in all_)
    avg    = (total / unique) if unique else 0.0
    # Pour l'instant, on met total_A=total et total_B=0
    embed = discord.Embed(
        title=messages.STATS["title"],
        color=messages.STATS["color"]
    )
    for field in messages.STATS["fields"]:
        value = field["value_template"].format(
            unique_users=unique,
            total_minutes=total,
            average_minutes=avg,
            total_A=total,
            total_B=0
        )
        embed.add_field(
            name=field["name"],
            value=value,
            inline=field["inline"]
        )
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', help='Afficher le Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top5 = classement_top10(ctx.guild.id)[:5]
    embed = discord.Embed(
        title=messages.LEADERBOARD["title"],
        color=messages.LEADERBOARD["color"]
    )
    if not top5:
        embed.description = "Aucun utilisateur."
    else:
        for i, (uid, mins) in enumerate(top5, start=1):
            user = await bot.fetch_user(uid)
            name = messages.LEADERBOARD["entry_template"]["name_template"].format(
                rank=i, username=user.name
            )
            val  = messages.LEADERBOARD["entry_template"]["value_template"].format(
                minutes=mins
            )
            embed.add_field(name=name, value=val, inline=False)
    await ctx.send(embed=embed)

# ─── COMMANDES ADMIN ───────────────────────────────────────────────────────────
@bot.command(name='maintenance', help='Activer/désactiver maintenance')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    tpl = messages.MAINT_TOGGLE
    await ctx.send(embed=discord.Embed(
        title=tpl["title"],
        description=tpl["description_template"].format(state=state),
        color=tpl["color"]
    ))

@bot.command(name='set_channel', help='Définir canal Pomodoro (admin)')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini','w') as f:
        config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    tpl = messages.SET_CHANNEL
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(channel_mention=channel.mention),
        color=tpl["color"]
    ))

@bot.command(name='set_role_A', help='Définir rôle A (admin)')
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini','w') as f:
        config.write(f)
    global POMODORO_ROLE_A
    POMODORO_ROLE_A = role.name
    tpl = messages.SET_ROLE_A
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(role_mention=role.mention),
        color=tpl["color"]
    ))

@bot.command(name='set_role_B', help='Définir rôle B (admin)')
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini','w') as f:
        config.write(f)
    global POMODORO_ROLE_B
    POMODORO_ROLE_B = role.name
    tpl = messages.SET_ROLE_B
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"].format(role_mention=role.mention),
        color=tpl["color"]
    ))

@bot.command(name='clear_stats', help='Réinitialiser toutes les statistiques (admin)')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    tpl = messages.CLEAR_STATS
    await ctx.send(embed=discord.Embed(
        description=tpl["description_template"],
        color=tpl["color"]
    ))

@bot.command(name='help', help='Afficher ce message')
async def help_cmd(ctx):
    embed = discord.Embed(
        title=messages.HELP["title"],
        color=messages.HELP["color"]
    )
    for f in messages.HELP["fields"]:
        embed.add_field(name=f["name"], value=f["value"], inline=f["inline"])
    await ctx.send(embed=embed)

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    if not channel or not (PARTICIPANTS_A or PARTICIPANTS_B):
        return

    # Mode A
    if PARTICIPANTS_A:
        SESSION_ACTIVE = True
        SESSION_PHASE = 'work'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=WORK_TIME_A)
        mention = (await ensure_role(channel.guild, POMODORO_ROLE_A)).mention
        await channel.send(messages.LOOP["start_template"].format(
            mode='A', duration=WORK_TIME_A, role_mention=mention
        ))
        await asyncio.sleep(WORK_TIME_A * 60)

        SESSION_PHASE = 'break'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=BREAK_TIME_A)
        await channel.send(messages.LOOP["pause_template"].format(
            mode='A', duration=BREAK_TIME_A, role_mention=mention
        ))
        await asyncio.sleep(BREAK_TIME_A * 60)

        for uid in PARTICIPANTS_A:
            ajouter_temps(uid, channel.guild.id, WORK_TIME_A)

    # Mode B
    if PARTICIPANTS_B:
        SESSION_ACTIVE = True
        SESSION_PHASE = 'work'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=WORK_TIME_B)
        mention = (await ensure_role(channel.guild, POMODORO_ROLE_B)).mention
        await channel.send(messages.LOOP["start_template"].format(
            mode='B', duration=WORK_TIME_B, role_mention=mention
        ))
        await asyncio.sleep(WORK_TIME_B * 60)

        SESSION_PHASE = 'break'
        SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=BREAK_TIME_B)
        await channel.send(messages.LOOP["pause_template"].format(
            mode='B', duration=BREAK_TIME_B, role_mention=mention
        ))
        await asyncio.sleep(BREAK_TIME_B * 60)

        for uid in PARTICIPANTS_B:
            ajouter_temps(uid, channel.guild.id, WORK_TIME_B)

    SESSION_ACTIVE = False

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
