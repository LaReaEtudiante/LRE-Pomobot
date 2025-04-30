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

WORK_TIME_A      = config['CURRENT_SETTINGS'].getint('work_time_A', fallback=50)
BREAK_TIME_A     = config['CURRENT_SETTINGS'].getint('break_time_A', fallback=10)
POMO_ROLE_A      = config['CURRENT_SETTINGS'].get('pomodoro_role_A',   fallback='50-10')
WORK_TIME_B      = config['CURRENT_SETTINGS'].getint('work_time_B', fallback=25)
BREAK_TIME_B     = config['CURRENT_SETTINGS'].getint('break_time_B', fallback=5)
POMO_ROLE_B      = config['CURRENT_SETTINGS'].get('pomodoro_role_B',   fallback='25-5')
POMODORO_CHANNEL = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
PREFIX           = config['CURRENT_SETTINGS'].get('prefix', '*')

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
SESSION_ACTIVE    = False
# Sessions séparées par mode
SESSION_PHASE_A   = None  # 'work' ou 'break'
SESSION_END_A     = None
SESSION_PHASE_B   = None
SESSION_END_B     = None

PARTICIPANTS_A    = set()
PARTICIPANTS_B    = set()

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
    # restaurer participants
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
    # Choix du template
    key = (
        "command_not_found" if isinstance(error, commands.CommandNotFound)
        else "maintenance_active" if isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance."
        else "missing_argument" if isinstance(error, commands.MissingRequiredArgument)
        else "permission_denied" if isinstance(error, commands.CheckFailure)
        else "unexpected_error"
    )
    err = messages.ERRORS[key]
    e = discord.Embed(
        title=err.get("title",""),
        description=err.get("description","") or err.get("description_template","").format(prefix=PREFIX, error=str(error)),
        color=err["color"]
    )
    await ctx.send(embed=e)

# ─── COMMANDES ÉTUDIANTS ───────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(f"⚠️ {user.mention} vous êtes déjà inscrit.")
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    tpl = messages.JOIN["A"]
    await ctx.send(f"✅ {tpl['description_template'].format(user_mention=user.mention)}")

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(f"⚠️ {user.mention} vous êtes déjà inscrit.")
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id, 'B')
    role = await ensure_role(ctx.guild, POMO_ROLE_B)
    await user.add_roles(role)
    tpl = messages.JOIN["B"]
    await ctx.send(f"✅ {tpl['description_template'].format(user_mention=user.mention)}")

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(f"⚠️ {user.mention} vous n'étiez pas inscrit.")
    now_ts = datetime.now(timezone.utc).timestamp()
    mins = max(int((now_ts - join_ts)//60), 1)
    ajouter_temps(user.id, ctx.guild.id, mins)
    # nettoyage participants + rôle
    if mode == 'A':
        PARTICIPANTS_A.discard(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_A)
    else:
        PARTICIPANTS_B.discard(user.id)
        role = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_B)
    if role: await user.remove_roles(role)
    await ctx.send(f"✅ {messages.LEAVE['description_template'].format(user_mention=user.mention, minutes=mins)}")

@bot.command(name='time', help='Temps restant des sessions A & B')
@check_maintenance()
async def time_left(ctx):
    now = datetime.now(timezone.utc)
    # Mode A
    if SESSION_END_A and now < SESSION_END_A:
        remA = SESSION_END_A - now
        mA, sA = divmod(int(remA.total_seconds()), 60)
        descA = f"{mA} min {sA} sec restantes ({SESSION_PHASE_A})"
    else:
        descA = "Aucune session"
    # Mode B
    if SESSION_END_B and now < SESSION_END_B:
        remB = SESSION_END_B - now
        mB, sB = divmod(int(remB.total_seconds()), 60)
        descB = f"{mB} min {sB} sec restantes ({SESSION_PHASE_B})"
    else:
        descB = "Aucune session"
    # Envoi
    await ctx.send(
        f"⏱️ **Temps restant**\n"
        f"• Mode A – {descA}\n"
        f"• Mode B – {descB}"
    )

# ─── COMMANDE STATUS ─────────────────────────────────────────────────────────
@bot.command(name='status', help='Afficher latence et état du bot')
async def status(ctx):
    latency = round(bot.latency*1000)
    local   = datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Zurich'))
    # session globale = prochaine clôture (A ou B la plus proche)
    next_ends = None
    if SESSION_END_A and (not SESSION_END_B or SESSION_END_A < SESSION_END_B):
        next_ends = SESSION_END_A
    elif SESSION_END_B:
        next_ends = SESSION_END_B
    # préparation du contexte pour format()
    context = {
        "latency":      latency,
        "local_time":   local.strftime("%Y-%m-%d %H:%M:%S"),
        "session_status": "active" if (SESSION_END_A or SESSION_END_B) else "aucune",
        "ends_at":      next_ends.strftime("%H:%M:%S") if next_ends else "–"
    }
    # build embed
    e = discord.Embed(
        title=messages.STATUS["title"],
        color=messages.STATUS["color"]
    )
    for f in messages.STATUS["fields"]:
        # on autorise {ends_at} si ajouté dans les templates
        val = f["value_template"].format(**context)
        e.add_field(name=f["name"], value=val, inline=f["inline"])
    await ctx.send(embed=e)

# ─── STATS & LEADERBOARD ───────────────────────────────────────────────────────
@bot.command(name='stats', help='Vos stats détaillées')
@check_maintenance()
async def stats(ctx):
    db     = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    all_   = db.all()
    unique = len(all_)
    total  = sum(u['minutes'] for u in all_)
    avg    = (total/unique) if unique else 0
    # A vs B
    total_A = sum(u['minutes'] for u in db.all() if u.get("mode")=="A")
    total_B = sum(u['minutes'] for u in db.all() if u.get("mode")=="B")
    e = discord.Embed(
        title=messages.STATS["title"],
        color=messages.STATS["color"]
    )
    for f in messages.STATS["fields"]:
        val = f["value_template"].format(
            unique_users    = unique,
            total_minutes   = total,
            average_minutes = avg,
            total_A         = total_A,
            total_B         = total_B
        )
        e.add_field(name=f["name"], value=val, inline=f["inline"])
    await ctx.send(embed=e)

@bot.command(name='leaderboard', help='Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top5 = classement_top10(ctx.guild.id)[:5]
    if not top5:
        return await ctx.send("🏆 Leaderboard Pomodoro\nAucun utilisateur.")
    lines = []
    for i,(uid,mins) in enumerate(top5,1):
        user = await bot.fetch_user(uid)
        lines.append(f"**#{i}** {user.name} – {mins} min")
    await ctx.send("🏆 Leaderboard Pomodoro\n" + "\n".join(lines))

# ─── ADMIN ─────────────────────────────────────────────────────────────────────
@bot.command(name='maintenance', help='Mode maintenance on/off')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    await ctx.send(f"🔧 Mode Maintenance : {state}")

@bot.command(name='set_channel', help='Choisir canal (admin)')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini','w') as f: config.write(f)
    global POMODORO_CHANNEL; POMODORO_CHANNEL = channel.id
    await ctx.send(f"✅ Canal défini sur {channel.mention}")

@bot.command(name='set_role_A', help='Définir rôle A (admin)')
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global POMO_ROLE_A; POMO_ROLE_A = role.name
    await ctx.send(f"✅ Rôle A défini sur {role.mention}")

@bot.command(name='set_role_B', help='Définir rôle B (admin)')
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global POMO_ROLE_B; POMO_ROLE_B = role.name
    await ctx.send(f"✅ Rôle B défini sur {role.mention}")

@bot.command(name='clear_stats', help='Réinitialiser toutes les stats')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    await ctx.send("✅ Statistiques réinitialisées.")

@bot.command(name='help', help='Affiche ce message')
async def help_cmd(ctx):
    help_lines = []
    for section in messages.HELP["fields"]:
        help_lines.append(f"**{section['name']}**\n{section['value']}")
    await ctx.send(f"🛠️ {messages.HELP['title']}\n" + "\n\n".join(help_lines))

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE_A, SESSION_END_A, SESSION_PHASE_B, SESSION_END_B
    channel = bot.get_channel(POMODORO_CHANNEL) if POMODORO_CHANNEL else None
    if not channel or not (PARTICIPANTS_A or PARTICIPANTS_B):
        return

    SESSION_ACTIVE = True
    # Mode A
    if PARTICIPANTS_A:
        SESSION_PHASE_A = 'work'
        SESSION_END_A   = datetime.now(timezone.utc) + timedelta(minutes=WORK_TIME_A)
        mention = (await ensure_role(channel.guild, POMO_ROLE_A)).mention
        await channel.send(f"🟢 Début travail (A, {WORK_TIME_A} min) ! {mention}")
        await asyncio.sleep(WORK_TIME_A * 60)
        SESSION_PHASE_A = 'break'
        SESSION_END_A   = datetime.now(timezone.utc) + timedelta(minutes=BREAK_TIME_A)
        await channel.send(f"🟡 Début pause   (A, {BREAK_TIME_A} min) ! {mention}")
        await asyncio.sleep(BREAK_TIME_A * 60)
    else:
        SESSION_PHASE_A = None
        SESSION_END_A   = None

    # Mode B
    if PARTICIPANTS_B:
        SESSION_PHASE_B = 'work'
        SESSION_END_B   = datetime.now(timezone.utc) + timedelta(minutes=WORK_TIME_B)
        mention = (await ensure_role(channel.guild, POMO_ROLE_B)).mention
        await channel.send(f"🔵 Début travail (B, {WORK_TIME_B} min) ! {mention}")
        await asyncio.sleep(WORK_TIME_B * 60)
        SESSION_PHASE_B = 'break'
        SESSION_END_B   = datetime.now(timezone.utc) + timedelta(minutes=BREAK_TIME_B)
        await channel.send(f"🟠 Début pause   (B, {BREAK_TIME_B} min) ! {mention}")
        await asyncio.sleep(BREAK_TIME_B * 60)
    else:
        SESSION_PHASE_B = None
        SESSION_END_B   = None

    # enregistrement pour tous les participants de A & B
    for uid in list(PARTICIPANTS_A):
        ajouter_temps(uid, channel.guild.id, WORK_TIME_A)
    for uid in list(PARTICIPANTS_B):
        ajouter_temps(uid, channel.guild.id, WORK_TIME_B)
    SESSION_ACTIVE = False

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
