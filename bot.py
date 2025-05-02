import os
import discord
from discord.ext import commands, tasks
import configparser
import logging
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
import messages

# ─── CONFIG & GLOBALS ─────────────────────────────────────────────────────────
config = configparser.ConfigParser()
config.read('settings.ini')

WORK_TIME_A  = config['CURRENT_SETTINGS'].getint('work_time_A', fallback=50)
BREAK_TIME_A = config['CURRENT_SETTINGS'].getint('break_time_A', fallback=10)
POMO_ROLE_A  = config['CURRENT_SETTINGS'].get('pomodoro_role_A',   fallback='50-10')
WORK_TIME_B  = config['CURRENT_SETTINGS'].getint('work_time_B', fallback=25)
BREAK_TIME_B = config['CURRENT_SETTINGS'].getint('break_time_B', fallback=5)
POMO_ROLE_B  = config['CURRENT_SETTINGS'].get('pomodoro_role_B',   fallback='25-5')

POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
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

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# ─── STATE ─────────────────────────────────────────────────────────────────────
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
    """
    Récupère le rôle par nom ou le crée avec une couleur personnalisée (#206694).
    """
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        # Création du rôle avec la couleur #206694
        role = await guild.create_role(
            name=name,
            colour=discord.Colour(0x206694)
        )
        logger.info(f"Rôle '{name}' créé dans '{guild.name}' avec la couleur #206694")
    return role

def get_phase_and_remaining(now: datetime, mode: str) -> tuple[str, int]:
    m, sec = now.minute, now.second
    if mode == 'A':
        if m < 50:
            return 'travail', (50 - m) * 60 - sec
        return 'pause', (60 - m) * 60 - sec
    if mode == 'B':
        if m < 25:
            return 'travail', (25 - m) * 60 - sec
        if m < 30:
            return 'pause', (30 - m) * 60 - sec
        if m < 55:
            return 'travail', (55 - m) * 60 - sec
        return 'pause', (60 - m) * 60 - sec
    return 'travail', 0

# ─── EVENTS & ERROR HANDLING ───────────────────────────────────────────────────
@bot.event
async def on_ready():
    logger.info(f"{bot.user} connecté.")
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
    key = (
        "command_not_found" if isinstance(error, commands.CommandNotFound) else
        "maintenance_active" if isinstance(error, commands.CommandError) and str(error) == "Bot en mode maintenance." else
        "missing_argument" if isinstance(error, commands.MissingRequiredArgument) else
        "permission_denied" if isinstance(error, commands.CheckFailure) else
        "unexpected_error"
    )
    text = messages.TEXT.get(key, messages.TEXT["unexpected_error"]).format(
        prefix=PREFIX, error=str(error)
    )
    await ctx.send(text)

# ─── COMMANDES ÉTUDIANT ────────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(f"🚫 {user.mention}, déjà inscrit.")
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    await user.add_roles(await ensure_role(ctx.guild, POMO_ROLE_A))
    ph, rem = get_phase_and_remaining(datetime.now(timezone.utc), 'A')
    m, s = divmod(rem, 60)
    await ctx.send(f"✅ {user.mention} a rejoint (mode A – 50-10).\nActuellement en **{ph}**, reste {m} min {s} s")

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(f"🚫 {user.mention}, déjà inscrit.")
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id, 'B')
    await user.add_roles(await ensure_role(ctx.guild, POMO_ROLE_B))
    ph, rem = get_phase_and_remaining(datetime.now(timezone.utc), 'B')
    m, s = divmod(rem, 60)
    await ctx.send(f"✅ {user.mention} a rejoint (mode B – 25-5).\nActuellement en **{ph}**, reste {m} min {s} s")

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(f"🚫 {user.mention}, pas inscrit.")
    now_ts = datetime.now(timezone.utc).timestamp()
    secs = int(now_ts - join_ts)
    if mode == 'A':
        PARTICIPANTS_A.discard(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_A)
    else:
        PARTICIPANTS_B.discard(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_B)
    if role:
        await user.remove_roles(role)
    ajouter_temps(user.id, ctx.guild.id, secs)
    m, s = divmod(secs, 60)
    await ctx.send(f"👋 {user.mention} a quitté. +{m} min {s} s ajoutées.")

@bot.command(name='time', help='Temps restant A & B')
@check_maintenance()
async def time_left(ctx):
    now = datetime.now(timezone.utc)
    phA, rA = get_phase_and_remaining(now, 'A')
    phB, rB = get_phase_and_remaining(now, 'B')
    mA, sA = divmod(rA, 60)
    mB, sB = divmod(rB, 60)
    e = discord.Embed(
        title="⌛ Temps avant prochaine bascule",
        description=(
            f"**Mode A** ({phA}) : {mA} min {sA} s\n"
            f"**Mode B** ({phB}) : {mB} min {sB} s"
        ),
        color=messages.MsgColors.YELLOW.value
    )
    await ctx.send(embed=e)

# ─── COMMANDE STATUS ─────────────────────────────────────────────────────────
@bot.command(name='status', help='État du bot')
async def status(ctx):
    lat = round(bot.latency * 1000)
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('Europe/Zurich')).strftime("%Y-%m-%d %H:%M:%S")
    phA, rA = get_phase_and_remaining(now, 'A')
    phB, rB = get_phase_and_remaining(now, 'B')
    mA, sA = divmod(rA, 60)
    mB, sB = divmod(rB, 60)
    e = discord.Embed(title=messages.STATUS["title"], color=messages.STATUS["color"])
    e.add_field(name="Latence",          value=f"{lat} ms",       inline=True)
    e.add_field(name="Heure (Lausanne)", value=local,             inline=True)
    e.add_field(name="Mode A",           value=phA,                inline=False)
    e.add_field(name="Restant A",        value=f"{mA} min {sA} s", inline=True)
    e.add_field(name="Mode B",           value=phB,                inline=False)
    e.add_field(name="Restant B",        value=f"{mB} min {sB} s", inline=True)
    e.add_field(name="Participants A",   value=str(len(PARTICIPANTS_A)), inline=True)
    e.add_field(name="Participants B",   value=str(len(PARTICIPANTS_B)), inline=True)
    await ctx.send(embed=e)

# ─── STATS & LEADERBOARD ───────────────────────────────────────────────────────
@bot.command(name='stats', help='Voir vos statistiques')
@check_maintenance()
async def stats(ctx):
    db = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    all_     = db.all()
    unique   = len(all_)
    total_s  = sum(u.get('seconds', 0) for u in all_)
    totalA_s = sum(u.get('seconds', 0) for u in all_ if u.get('mode')=='A')
    totalB_s = sum(u.get('seconds', 0) for u in all_ if u.get('mode')=='B')
    total_m   = total_s / 60
    totalA_m  = totalA_s / 60
    totalB_m  = totalB_s / 60
    avg_m     = (total_m / unique) if unique else 0

    e = discord.Embed(title=messages.STATS["title"], color=messages.STATS["color"])
    for f in messages.STATS["fields"]:
        val = f["value_template"].format(
            unique_users    = unique,
            total_minutes   = total_m,
            average_minutes = avg_m,
            total_A         = totalA_m,
            total_B         = totalB_m
        )
        e.add_field(name=f["name"], value=val, inline=f["inline"])
    await ctx.send(embed=e)

@bot.command(name='leaderboard', help='Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top5 = [(uid, secs) for uid, secs in classement_top10(ctx.guild.id)][:5]
    e = discord.Embed(title=messages.LEADERBOARD["title"], color=messages.LEADERBOARD["color"])
    if not top5:
        e.description = "Aucun utilisateur."
    else:
        for i, (uid, secs) in enumerate(top5, 1):
            user = await bot.fetch_user(uid)
            m, s = divmod(secs, 60)
            name = messages.LEADERBOARD["entry_template"]["name_template"].format(rank=i, username=user.name)
            val  = f"{m} min {s} s"
            e.add_field(name=name, value=val, inline=False)
    await ctx.send(embed=e)

# ─── COMMANDES ADMIN ───────────────────────────────────────────────────────────
@bot.command(name='maintenance', help='Maintenance on/off')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    await ctx.send(messages.TEXT["maintenance_toggle"].format(
        state=("activée" if MAINTENANCE_MODE else "désactivée")
    ))

@bot.command(name='set_channel', help='Définir canal (admin)')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini', 'w') as f: config.write(f)
    global POMODORO_CHANNEL_ID; POMODORO_CHANNEL_ID = channel.id
    await ctx.send(messages.TEXT["set_channel"].format(channel_mention=channel.mention))

@bot.command(name='set_role_A', help='Définir rôle A (admin)')
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini', 'w') as f: config.write(f)
    global POMO_ROLE_A; POMO_ROLE_A = role.name
    await ctx.send(messages.TEXT["set_role_A"].format(role_mention=role.mention))

@bot.command(name='set_role_B', help='Définir rôle B (admin)')
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini', 'w') as f: config.write(f)
    global POMO_ROLE_B; POMO_ROLE_B = role.name
    await ctx.send(messages.TEXT["set_role_B"].format(role_mention=role.mention))

@bot.command(name='clear_stats', help='Réinitialiser stats (admin)')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    await ctx.send(messages.TEXT["clear_stats"])

@bot.command(name='help', help='Afficher aide')
async def help_cmd(ctx):
    e = discord.Embed(title=messages.HELP["title"], color=messages.HELP["color"])
    for f in messages.HELP["fields"]:
        e.add_field(name=f["name"], value=f["value"], inline=f["inline"])
    await ctx.send(embed=e)

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def pomodoro_loop():
    channel = bot.get_channel(POMODORO_CHANNEL_ID) if POMODORO_CHANNEL_ID else None
    if not channel:
        return

    now = datetime.now(timezone.utc)
    minute = now.minute

    if PARTICIPANTS_A:
        mention = (await ensure_role(channel.guild, POMO_ROLE_A)).mention
        if minute == 0:
            await channel.send(f"🔔 Mode A : début travail (50 min) {mention}")
        elif minute == 50:
            for uid in PARTICIPANTS_A:
                ajouter_temps(uid, channel.guild.id, WORK_TIME_A * 60)
            await channel.send(f"☕ Mode A : début pause (10 min) {mention}")

    if PARTICIPANTS_B:
        mention = (await ensure_role(channel.guild, POMO_ROLE_B)).mention
        if minute == 0:
            await channel.send(f"🔔 Mode B : début travail (25 min) {mention}")
        elif minute == 25:
            for uid in PARTICIPANTS_B:
                ajouter_temps(uid, channel.guild.id, WORK_TIME_B * 60)
            await channel.send(f"☕ Mode B : première pause (5 min) {mention}")
        elif minute == 30:
            await channel.send(f"🔔 Mode B : deuxième travail (25 min) {mention}")
        elif minute == 55:
            for uid in PARTICIPANTS_B:
                ajouter_temps(uid, channel.guild.id, WORK_TIME_B * 60)
            await channel.send(f"☕ Mode B : pause finale (5 min) {mention}")

if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))