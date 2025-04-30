import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from tinydb import TinyDB

import messages
from database import (
    ajouter_temps_A,
    ajouter_temps_B,
    classement_top10,
    add_participant,
    remove_participant,
    get_all_participants
)
from keep_alive import keep_alive

# ─── CONFIG & GLOBALS ────────────────────────────────────────────────────────
config = configparser.ConfigParser()
config.read('settings.ini')

WORK_TIME_A        = config['CURRENT_SETTINGS'].getint('work_time_A',   fallback=50)
BREAK_TIME_A       = config['CURRENT_SETTINGS'].getint('break_time_A',  fallback=10)
POMO_ROLE_A        = config['CURRENT_SETTINGS'].get('pomodoro_role_A', fallback='50-10')
WORK_TIME_B        = config['CURRENT_SETTINGS'].getint('work_time_B',   fallback=25)
BREAK_TIME_B       = config['CURRENT_SETTINGS'].getint('break_time_B',  fallback=5)
POMO_ROLE_B        = config['CURRENT_SETTINGS'].get('pomodoro_role_B', fallback='25-5')
POMODORO_CHANNEL_ID= config['CURRENT_SETTINGS'].getint('channel_id',   fallback=None)
PREFIX             = config['CURRENT_SETTINGS'].get('prefix', '*')
MAINTENANCE_MODE   = False

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, help_command=None,
                   intents=intents, case_insensitive=True)

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# ─── STATE ───────────────────────────────────────────────────────────────────
SESSION_ACTIVE = False
SESSION_PHASE  = None   # 'work' ou 'break'
SESSION_END    = None
PARTICIPANTS_A = set()
PARTICIPANTS_B = set()

# ─── UTILITAIRES ──────────────────────────────────────────────────────────────
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

# ─── EVENTS ─────────────────────────────────────────────────────────────────
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
    key = (
        "command_not_found" if isinstance(error, commands.CommandNotFound) else
        "maintenance_active" if isinstance(error, commands.CommandError) and str(error) == "Bot en mode maintenance." else
        "missing_argument" if isinstance(error, commands.MissingRequiredArgument) else
        "permission_denied" if isinstance(error, commands.CheckFailure) else
        "unexpected_error"
    )
    err = messages.ERRORS[key]
    e = discord.Embed(
        title=err.get("title", ""),
        description=err.get("description_template", "").format(prefix=PREFIX, error=str(error)),
        color=err["color"]
    )
    await ctx.send(embed=e)

# ─── COMMANDES ÉTUDIANT ───────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send("❗ Vous êtes déjà inscrit.")
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    tpl = messages.JOIN["A"]
    await ctx.send(f"{tpl['description_template'].format(user_mention=user.mention)}")

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send("❗ Vous êtes déjà inscrit.")
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id, 'B')
    role = await ensure_role(ctx.guild, POMO_ROLE_B)
    await user.add_roles(role)
    tpl = messages.JOIN["B"]
    await ctx.send(f"{tpl['description_template'].format(user_mention=user.mention)}")

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send("❗ Vous n'étiez pas inscrit.")
    now_ts = datetime.now(timezone.utc).timestamp()
    mins = max(int((now_ts - join_ts) // 60), 1)
    # Enregistrement selon le mode
    if mode == 'A':
        PARTICIPANTS_A.discard(user.id)
        ajouter_temps_A(user.id, ctx.guild.id, mins)
    else:
        PARTICIPANTS_B.discard(user.id)
        ajouter_temps_B(user.id, ctx.guild.id, mins)
    tpl = messages.LEAVE
    await ctx.send(f"{tpl['description_template'].format(user_mention=user.mention, minutes=mins)}")

@bot.command(name='time', help='Temps restant session')
@check_maintenance()
async def time_left(ctx):
    if not SESSION_ACTIVE or SESSION_PHASE is None:
        return await ctx.send("ℹ️ Aucune session en cours.")
    now = datetime.now(timezone.utc)
    rem = max(int((SESSION_END - now).total_seconds()), 0)
    m, s = divmod(rem, 60)
    phase = SESSION_PHASE
    nxt = 'pause' if phase == 'work' else 'travail'
    tpl = messages.TIME_LEFT
    await ctx.send(
        tpl["title_template"].format(phase=phase) + " — " +
        tpl["description_template"].format(next_phase=nxt, minutes=m, seconds=s)
    )

# ─── COMMANDE STATUS ─────────────────────────────────────────────────────────
@bot.command(name='status', help='Afficher latence et état du bot')
async def status(ctx):
    latency = round(bot.latency * 1000)
    local   = datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Zurich'))
    if SESSION_ACTIVE and SESSION_END:
        rem = max(int((SESSION_END - datetime.now(timezone.utc)).total_seconds()), 0)
        m, s = divmod(rem, 60)
        sess = f"{SESSION_PHASE} dans {m} min {s} sec"
    else:
        sess = "aucune session active"
    e = discord.Embed(title=messages.STATUS["title"], color=messages.STATUS["color"])
    for f in messages.STATUS["fields"]:
        val = f["value_template"].format(
            latency=latency,
            local_time=local.strftime("%Y-%m-%d %H:%M:%S"),
            session_status=sess
        )
        e.add_field(name=f["name"], value=val, inline=f["inline"])
    await ctx.send(embed=e)

# ─── STATS & LEADERBOARD ───────────────────────────────────────────────────────
@bot.command(name='stats', help='Vos stats')
@check_maintenance()
async def stats(ctx):
    guild_id = str(ctx.guild.id)
    # lecture séparée
    tableA = TinyDB('leaderboard_A.json').table(guild_id)
    tableB = TinyDB('leaderboard_B.json').table(guild_id)
    usersA = tableA.all()
    usersB = tableB.all()

    uids    = {r['user_id'] for r in usersA} | {r['user_id'] for r in usersB}
    unique  = len(uids)
    totalA  = sum(r['minutes'] for r in usersA)
    totalB  = sum(r['minutes'] for r in usersB)
    total   = totalA + totalB
    avg     = (total / unique) if unique else 0

    e = discord.Embed(title=messages.STATS["title"], color=messages.STATS["color"])
    for f in messages.STATS["fields"]:
        val = f["value_template"].format(
            unique_users    = unique,
            total_minutes   = total,
            average_minutes = avg,
            total_A         = totalA,
            total_B         = totalB
        )
        e.add_field(name=f["name"], value=val, inline=f["inline"])
    await ctx.send(embed=e)

@bot.command(name='leaderboard', help='Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top5 = classement_top10(ctx.guild.id)[:5]
    e = discord.Embed(title=messages.LEADERBOARD["title"], color=messages.LEADERBOARD["color"])
    if not top5:
        e.description = "Aucun utilisateur."
    else:
        for i, (uid, mins) in enumerate(top5, 1):
            user = await bot.fetch_user(uid)
            e.add_field(
                name=messages.LEADERBOARD["entry_template"]["name_template"].format(rank=i, username=user.name),
                value=messages.LEADERBOARD["entry_template"]["value_template"].format(minutes=mins),
                inline=False
            )
    await ctx.send(embed=e)

# ─── COMMANDES ADMIN ───────────────────────────────────────────────────────────
@bot.command(name='maintenance', help='Mode maintenance on/off')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    tpl = messages.MAINT_TOGGLE
    await ctx.send(f"🔧 Mode Maintenance : Mode maintenance {state}.")

@bot.command(name='set_channel', help='Choisir canal (admin)')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    await ctx.send(f"✅ Canal défini sur {channel.mention}.")

@bot.command(name='set_role_A', help='Définir rôle A (admin)')
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMO_ROLE_A
    POMO_ROLE_A = role.name
    await ctx.send(f"✅ Rôle A défini sur {role.mention}.")

@bot.command(name='set_role_B', help='Définir rôle B (admin)')
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMO_ROLE_B
    POMO_ROLE_B = role.name
    await ctx.send(f"✅ Rôle B défini sur {role.mention}.")

@bot.command(name='clear_stats', help='Réinitialiser toutes les stats')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard_A.json').drop_table(str(ctx.guild.id))
    TinyDB('leaderboard_B.json').drop_table(str(ctx.guild.id))
    await ctx.send("✅ Toutes les statistiques ont été réinitialisées.")

@bot.command(name='help', help='Affiche ce message')
async def help_cmd(ctx):
    e = discord.Embed(title=messages.HELP["title"], color=messages.HELP["color"])
    for f in messages.HELP["fields"]:
        e.add_field(name=f["name"], value=f["value"], inline=f["inline"])
    await ctx.send(embed=e)

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    cid = POMODORO_CHANNEL_ID
    channel = bot.get_channel(cid) if cid else None
    if not channel or not (PARTICIPANTS_A or PARTICIPANTS_B):
        return

    for mode, participants, work, pause, role_name, save_fn in (
        ('A', PARTICIPANTS_A, WORK_TIME_A, BREAK_TIME_A, POMO_ROLE_A, ajouter_temps_A),
        ('B', PARTICIPANTS_B, WORK_TIME_B, BREAK_TIME_B, POMO_ROLE_B, ajouter_temps_B),
    ):
        if not participants:
            continue

        SESSION_ACTIVE = True
        SESSION_PHASE  = 'work'
        SESSION_END    = datetime.now(timezone.utc) + timedelta(minutes=work)
        mention        = (await ensure_role(channel.guild, role_name)).mention
        await channel.send(f"▶️ Début travail ({mode}, {work} min) ! {mention}")
        await asyncio.sleep(work * 60)

        SESSION_PHASE = 'break'
        SESSION_END   = datetime.now(timezone.utc) + timedelta(minutes=pause)
        await channel.send(f"☕ Début pause ({mode}, {pause} min) ! {mention}")
        await asyncio.sleep(pause * 60)

        for uid in list(participants):
            save_fn(uid, channel.guild.id, work)

    SESSION_ACTIVE = False

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
