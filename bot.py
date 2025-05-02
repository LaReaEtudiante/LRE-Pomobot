import os
import discord
from discord.ext import commands, tasks
import configparser
import logging
import asyncio
from datetime import datetime, timezone
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

WORK_TIME_A         = config['CURRENT_SETTINGS'].getint('work_time_A', fallback=50)
BREAK_TIME_A        = config['CURRENT_SETTINGS'].getint('break_time_A', fallback=10)
POMO_ROLE_A         = config['CURRENT_SETTINGS'].get('pomodoro_role_A',   fallback='50-10')
WORK_TIME_B         = config['CURRENT_SETTINGS'].getint('work_time_B', fallback=25)
BREAK_TIME_B        = config['CURRENT_SETTINGS'].getint('break_time_B', fallback=5)
POMO_ROLE_B         = config['CURRENT_SETTINGS'].get('pomodoro_role_B',   fallback='25-5')
POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id',      fallback=None)
PREFIX              = config['CURRENT_SETTINGS'].get('prefix',            '*')
MAINTENANCE_MODE    = False

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
PARTICIPANTS_A = set()
PARTICIPANTS_B = set()

# ─── EXCEPTIONS ─────────────────────────────────────────────────────────────────
class SetupIncomplete(commands.CommandError):
    """La configuration initiale (canal et rôles) est incomplète."""

class WrongChannel(commands.CommandError):
    """Commande utilisée dans un canal non autorisé."""

# ─── DÉCORATEURS UTILS ─────────────────────────────────────────────────────────
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

def check_setup():
    async def predicate(ctx):
        guild = ctx.guild
        channel_ok = POMODORO_CHANNEL_ID and bot.get_channel(POMODORO_CHANNEL_ID)
        roleA_ok  = discord.utils.get(guild.roles, name=POMO_ROLE_A)
        roleB_ok  = discord.utils.get(guild.roles, name=POMO_ROLE_B)
        if channel_ok and roleA_ok and roleB_ok:
            return True
        raise SetupIncomplete()
    return commands.check(predicate)

def check_channel():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator or ctx.command.name in ('status', 'help'):
            return True
        if ctx.channel.id == POMODORO_CHANNEL_ID:
            return True
        raise WrongChannel()
    return commands.check(predicate)

async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(
            name=name,
            colour=discord.Colour(0x206694)
        )
        logger.info(f"Rôle '{name}' créé avec couleur #206694 dans '{guild.name}'")
    return role

def get_phase_and_remaining(now: datetime, mode: str) -> tuple[str, int]:
    m, sec = now.minute, now.second
    if mode == 'A':
        if m < 50:
            return 'travail', (50 - m) * 60 - sec
        return 'pause',  (60 - m) * 60 - sec
    if mode == 'B':
        if m < 25:
            return 'travail', (25 - m) * 60 - sec
        if m < 30:
            return 'pause',  (30 - m) * 60 - sec
        if m < 55:
            return 'travail', (55 - m) * 60 - sec
        return 'pause',  (60 - m) * 60 - sec
    return 'travail', 0

# ─── EVENTS & GESTION D’ERREURS ─────────────────────────────────────────────────
@bot.event
async def on_ready():
    logger.info(f"{bot.user} connecté.")
    for guild in bot.guilds:
        for uid, mode in get_all_participants(guild.id):
            (PARTICIPANTS_A if mode == 'A' else PARTICIPANTS_B).add(uid)
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, SetupIncomplete):
        return await ctx.send(messages.TEXT["setup_incomplete"])
    if isinstance(error, WrongChannel):
        ch = bot.get_channel(POMODORO_CHANNEL_ID)
        return await ctx.send(f"❌ Veuillez utiliser les commandes dans {ch.mention}.")
    key = (
        "command_not_found"   if isinstance(error, commands.CommandNotFound) else
        "maintenance_active"  if isinstance(error, commands.CommandError) and str(error) == "Bot en mode maintenance." else
        "missing_argument"    if isinstance(error, commands.MissingRequiredArgument) else
        "permission_denied"   if isinstance(error, commands.CheckFailure) else
        "unexpected_error"
    )
    text = messages.TEXT.get(key, messages.TEXT["unexpected_error"]).format(
        prefix=PREFIX, error=str(error)
    )
    await ctx.send(text)

# ─── COMMANDES ÉTUDIANT ────────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
@check_setup()
@check_channel()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(f"🚫 {user.mention}, déjà inscrit.")
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    await user.add_roles(await ensure_role(ctx.guild, POMO_ROLE_A))
    ph, rem = get_phase_and_remaining(datetime.now(timezone.utc), 'A')
    m, s = divmod(rem, 60)
    await ctx.send(f"✅ {user.mention} a rejoint (mode A).\nActuellement en **{ph}**, reste {m} min {s} s")

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
@check_setup()
@check_channel()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A | PARTICIPANTS_B:
        return await ctx.send(f"🚫 {user.mention}, déjà inscrit.")
    PARTICIPANTS_B.add(user.id)
    add_participant(user.id, ctx.guild.id, 'B')
    await user.add_roles(await ensure_role(ctx.guild, POMO_ROLE_B))
    ph, rem = get_phase_and_remaining(datetime.now(timezone.utc), 'B')
    m, s = divmod(rem, 60)
    await ctx.send(f"✅ {user.mention} a rejoint (mode B).\nActuellement en **{ph}**, reste {m} min {s} s")

@bot.command(name='leave', help='Quitter la session Pomodoro')
@check_maintenance()
@check_setup()
@check_channel()
async def leave(ctx):
    user = ctx.author
    join_ts, mode = remove_participant(user.id, ctx.guild.id)
    if join_ts is None:
        return await ctx.send(f"🚫 {user.mention}, pas inscrit.")
    secs = int(datetime.now(timezone.utc).timestamp() - join_ts)
    (PARTICIPANTS_A if mode == 'A' else PARTICIPANTS_B).discard(user.id)
    role_name = POMO_ROLE_A if mode == 'A' else POMO_ROLE_B
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role:
        await user.remove_roles(role)
    ajouter_temps(user.id, ctx.guild.id, secs)
    m, s = divmod(secs, 60)
    await ctx.send(f"👋 {user.mention} a quitté. +{m} min {s} s ajoutées.")

@bot.command(name='time', help='Temps restant avant bascule')
@check_maintenance()
@check_setup()
@check_channel()
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

@bot.command(name='status', help='Afficher état et configuration')
async def status(ctx):
    latency = round(bot.latency * 1000)
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('Europe/Zurich')).strftime("%Y-%m-%d %H:%M:%S")

    # Calcul des phases et temps restants
    phA, rA = get_phase_and_remaining(now, 'A')
    phB, rB = get_phase_and_remaining(now, 'B')
    mA, sA = divmod(rA, 60)
    mB, sB = divmod(rB, 60)

    # Comptes de participants
    countA = len(PARTICIPANTS_A)
    countB = len(PARTICIPANTS_B)

    # Vérification configuration
    chan = bot.get_channel(POMODORO_CHANNEL_ID)
    chan_field = f"✅ {chan.mention}" if chan else "❌ non configuré"
    guild = ctx.guild
    roleA = discord.utils.get(guild.roles, name=POMO_ROLE_A)
    roleB = discord.utils.get(guild.roles, name=POMO_ROLE_B)
    roleA_field = f"✅ {roleA.mention}" if roleA else "❌ non configuré"
    roleB_field = f"✅ {roleB.mention}" if roleB else "❌ non configuré"

    e = discord.Embed(title=messages.STATUS["title"], color=messages.STATUS["color"])
    e.add_field(name="Latence",          value=f"{latency} ms",                                             inline=True)
    e.add_field(name="Heure (Lausanne)", value=local,                                                       inline=True)
    e.add_field(
        name="Mode A",
        value=f"{countA} participants en **{phA}** pour {mA} min {sA} s",
        inline=False
    )
    e.add_field(
        name="Mode B",
        value=f"{countB} participants en **{phB}** pour {mB} min {sB} s",
        inline=False
    )
    e.add_field(name="Canal Pomodoro",   value=chan_field,                                                  inline=False)
    e.add_field(name="Rôle A",           value=roleA_field,                                                 inline=False)
    e.add_field(name="Rôle B",           value=roleB_field,                                                 inline=False)
    await ctx.send(embed=e)

@bot.command(name='stats', help='Voir vos statistiques')
@check_maintenance()
@check_setup()
@check_channel()
async def stats(ctx):
    db = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    all_     = db.all()
    unique   = len(all_)
    total_s  = sum(u.get('seconds', 0) for u in all_)
    totalA_s = sum(u.get('seconds', 0) for u in all_ if u.get('mode') == 'A')
    totalB_s = sum(u.get('seconds', 0) for u in all_ if u.get('mode') == 'B')
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

@bot.command(name='leaderboard', help='Afficher top 5 général')
@check_maintenance()
@check_setup()
@check_channel()
async def leaderboard(ctx):
    top5 = classement_top10(ctx.guild.id)[:5]
    e = discord.Embed(title=messages.LEADERBOARD["title"], color=messages.LEADERBOARD["color"])
    if not top5:
        e.description = "Aucun utilisateur."
    else:
        for i, (uid, secs) in enumerate(top5, 1):
            user = await bot.fetch_user(uid)
            m, s = divmod(secs, 60)
            name = messages.LEADERBOARD["entry_template"]["name_template"].format(
                rank=i, username=user.name
            )
            val  = f"{m} min {s} s"
            e.add_field(name=name, value=val, inline=False)
    await ctx.send(embed=e)

# ─── COMMANDES ADMIN ───────────────────────────────────────────────────────────
@bot.command(name='maintenance', help='Activer/désactiver maintenance')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    await ctx.send(messages.TEXT["maintenance_toggle"].format(state=state))

@bot.command(name='set_channel', help='Définir canal Pomodoro (admin)')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini', 'w') as f:
        config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    await ctx.send(messages.TEXT["set_channel"].format(channel_mention=channel.mention))

@bot.command(name='set_role_A', help='Définir rôle A (admin)')
@is_admin()
async def set_role_A(ctx, role: discord.Role = None):
    global POMO_ROLE_A

    if role is None:
        existing = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_A)
        if existing:
            await ctx.send(
                f"🎛️ J'ai trouvé un rôle existant {existing.mention} "
                f"correspondant à `{POMO_ROLE_A}`. Voulez-vous l'utiliser ? (oui/non)"
            )
            try:
                reply = await bot.wait_for(
                    'message',
                    check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                    timeout=60
                )
            except asyncio.TimeoutError:
                return await ctx.send("⏱️ Délai écoulé. Réessayez `*set_role_A @VotreRôle`.")
            if reply.content.lower() in ('oui','o','yes','y'):
                config['CURRENT_SETTINGS']['pomodoro_role_A'] = existing.name
                with open('settings.ini','w') as f: config.write(f)
                POMO_ROLE_A = existing.name
                return await ctx.send(f"✅ Rôle A configuré : {existing.mention}")

        await ctx.send(
            f"⚙️ Vous n’avez pas spécifié de rôle A.\n"
            f"Voulez-vous que je crée un rôle `{POMO_ROLE_A}` pour vous ? (oui/non)"
        )
        try:
            reply2 = await bot.wait_for(
                'message',
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                timeout=60
            )
        except asyncio.TimeoutError:
            return await ctx.send("⏱️ Délai écoulé. Réessayez `*set_role_A @VotreRôle`.")
        if reply2.content.lower() in ('oui','o','yes','y'):
            new_role = await ensure_role(ctx.guild, POMO_ROLE_A)
            config['CURRENT_SETTINGS']['pomodoro_role_A'] = new_role.name
            with open('settings.ini','w') as f: config.write(f)
            POMO_ROLE_A = new_role.name
            return await ctx.send(f"✅ Rôle A créé et configuré : {new_role.mention}")
        else:
            return await ctx.send("❌ Aucun rôle configuré. Réexécutez `*set_role_A @VotreRôle`.")

    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini','w') as f:
        config.write(f)
    POMO_ROLE_A = role.name
    await ctx.send(messages.TEXT["set_role_A"].format(role_mention=role.mention))

@bot.command(name='set_role_B', help='Définir rôle B (admin)')
@is_admin()
async def set_role_B(ctx, role: discord.Role = None):
    global POMO_ROLE_B

    if role is None:
        existing = discord.utils.get(ctx.guild.roles, name=POMO_ROLE_B)
        if existing:
            await ctx.send(
                f"🎛️ J'ai trouvé un rôle existant {existing.mention} "
                f"correspondant à `{POMO_ROLE_B}`. Voulez-vous l'utiliser ? (oui/non)"
            )
            try:
                reply = await bot.wait_for(
                    'message',
                    check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                    timeout=60
                )
            except asyncio.TimeoutError:
                return await ctx.send("⏱️ Délai écoulé. Réessayez `*set_role_B @VotreRôle`.")
            if reply.content.lower() in ('oui','o','yes','y'):
                config['CURRENT_SETTINGS']['pomodoro_role_B'] = existing.name
                with open('settings.ini','w') as f: config.write(f)
                POMO_ROLE_B = existing.name
                return await ctx.send(f"✅ Rôle B configuré : {existing.mention}")

        await ctx.send(
            f"⚙️ Vous n’avez pas spécifié de rôle B.\n"
            f"Voulez-vous que je crée un rôle `{POMO_ROLE_B}` pour vous ? (oui/non)"
        )
        try:
            reply2 = await bot.wait_for(
                'message',
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                timeout=60
            )
        except asyncio.TimeoutError:
            return await ctx.send("⏱️ Délai écoulé. Réessayez `*set_role_B @VotreRôle`.")
        if reply2.content.lower() in ('oui','o','yes','y'):
            new_role = await ensure_role(ctx.guild, POMO_ROLE_B)
            config['CURRENT_SETTINGS']['pomodoro_role_B'] = new_role.name
            with open('settings.ini','w') as f: config.write(f)
            POMO_ROLE_B = new_role.name
            return await ctx.send(f"✅ Rôle B créé et configuré : {new_role.mention}")
        else:
            return await ctx.send("❌ Aucun rôle configuré. Réexécutez `*set_role_B @VotreRôle`.")

    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini','w') as f:
        config.write(f)
    POMO_ROLE_B = role.name
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
    now = datetime.now(timezone.utc)
    minute = now.minute

    # Mode A
    if PARTICIPANTS_A:
        mention = (await ensure_role(bot.get_guild(bot.guilds[0].id), POMO_ROLE_A)).mention
        if minute == 0:
            await bot.get_channel(POMODORO_CHANNEL_ID).send(
                f"🔔 Mode A : début travail (50 min) {mention}"
            )
        elif minute == 50:
            for uid in PARTICIPANTS_A:
                ajouter_temps(uid, bot.get_guild(bot.guilds[0].id).id, WORK_TIME_A * 60)
            await bot.get_channel(POMODORO_CHANNEL_ID).send(
                f"☕ Mode A : début pause (10 min) {mention}"
            )

    # Mode B
    if PARTICIPANTS_B:
        mention = (await ensure_role(bot.get_guild(bot.guilds[0].id), POMO_ROLE_B)).mention
        if minute == 0:
            await bot.get_channel(POMODORO_CHANNEL_ID).send(
                f"🔔 Mode B : début travail (25 min) {mention}"
            )
        elif minute == 25:
            for uid in PARTICIPANTS_B:
                ajouter_temps(uid, bot.get_guild(bot.guilds[0].id).id, WORK_TIME_B * 60)
            await bot.get_channel(POMODORO_CHANNEL_ID).send(
                f"☕ Mode B : première pause (5 min) {mention}"
            )
        elif minute == 30:
            await bot.get_channel(POMODORO_CHANNEL_ID).send(
                f"🔔 Mode B : deuxième travail (25 min) {mention}"
            )
        elif minute == 55:
            for uid in PARTICIPANTS_B:
                ajouter_temps(uid, bot.get_guild(bot.guilds[0].id).id, WORK_TIME_B * 60)
            await bot.get_channel(POMODORO_CHANNEL_ID).send(
                f"☕ Mode B : pause finale (5 min) {mention}"
            )

if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))