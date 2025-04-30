# bot.py

import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

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

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
config = configparser.ConfigParser()
config.read('settings.ini')

WORK_TIME_A  = config['CURRENT_SETTINGS'].getint('work_time_A',   fallback=50)
BREAK_TIME_A = config['CURRENT_SETTINGS'].getint('break_time_A',  fallback=10)
POMO_ROLE_A  = config['CURRENT_SETTINGS'].get('pomodoro_role_A', fallback='50-10')

WORK_TIME_B  = config['CURRENT_SETTINGS'].getint('work_time_B',   fallback=25)
BREAK_TIME_B = config['CURRENT_SETTINGS'].getint('break_time_B',  fallback=5)
POMO_ROLE_B  = config['CURRENT_SETTINGS'].get('pomodoro_role_B', fallback='25-5')

POMODORO_CHANNEL_ID = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
PREFIX              = config['CURRENT_SETTINGS'].get('prefix', '*')
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
    '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# ─── ÉTAT ───────────────────────────────────────────────────────────────────────
SESSION_ACTIVE = False
SESSION_PHASE  = None  # 'work' ou 'break'
SESSION_END    = None
PARTICIPANTS_A = set()
PARTICIPANTS_B = set()


# ─── UTILITAIRES ─────────────────────────────────────────────────────────────────
def is_admin():
    async def pred(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(pred)

def check_maintenance():
    async def pred(ctx):
        if MAINTENANCE_MODE and ctx.command.name != 'maintenance':
            raise commands.CommandError("Bot en mode maintenance.")
        return True
    return commands.check(pred)

async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name)
        logger.info(f"Rôle '{name}' créé dans '{guild.name}'")
    return role

# ─── ÉVÉNEMENTS ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global MAINTENANCE_MODE
    logger.info(f"{bot.user} connecté.")
    # restaurer les participants
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
        "maintenance_active" if isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance." else
        "missing_argument" if isinstance(error, commands.MissingRequiredArgument) else
        "permission_denied" if isinstance(error, commands.CheckFailure) else
        "unexpected_error"
    )
    err = messages.ERRORS[key]
    e = discord.Embed(
        title=err.get("title",""),
        description=err.get("description", err.get("description_template","")).format(prefix=PREFIX, error=str(error)),
        color=err["color"]
    )
    await ctx.send(embed=e)


# ─── COMMANDES ÉTUDIANT ─────────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre mode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send("❗ Vous êtes déjà inscrit.")
    PARTICIPANTS_A.add(user.id)
    add_participant(user.id, ctx.guild.id, 'A')
    role = await ensure_role(ctx.guild, POMO_ROLE_A)
    await user.add_roles(role)
    tpl = messages.JOIN["A"]
    await ctx.send(f"✅ {tpl['description_template'].format(user_mention=user.mention)}")


@bot.command(name='joinB', help='Rejoindre mode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    user = ctx.author
    if user.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send("❗ Vous êtes déjà inscrit.")
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
        return await ctx.send("❗ Vous n'étiez pas inscrit.")
    mins = max(int((datetime.now(timezone.utc).timestamp() - join_ts)//60), 1)
    ajouter_temps(user.id, ctx.guild.id, mins)
    # retirer rôle et du set
    if mode=='A':
        PARTICIPANTS_A.discard(user.id)
        r = POMO_ROLE_A
    else:
        PARTICIPANTS_B.discard(user.id)
        r = POMO_ROLE_B
    await ctx.author.remove_roles(discord.utils.get(ctx.guild.roles,name=r))
    tpl = messages.LEAVE
    await ctx.send(f"✅ {tpl['description_template'].format(user_mention=user.mention, minutes=mins)}")


@bot.command(name='time', help='Temps restant des deux modes')
@check_maintenance()
async def time_left(ctx):
    if not SESSION_ACTIVE:
        return await ctx.send("ℹ️ Aucune session en cours.")
    rem = max(int((SESSION_END - datetime.now(timezone.utc)).total_seconds()),0)
    m,s = divmod(rem,60)
    await ctx.send(f"⏱️ Il reste {m} min {s} sec avant la fin de la session {SESSION_PHASE}.")


@bot.command(name='status', help='État complet du bot')
async def status(ctx):
    latency = round(bot.latency*1000)
    now = datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Zurich'))
    sess = "aucune" if not SESSION_ACTIVE else f"{SESSION_PHASE} ({max(int((SESSION_END-datetime.now(timezone.utc)).total_seconds()),0)//60} min restantes)"
    msg = f"🏷️ **Latence:** {latency} ms\n" \
          f"🕒 **Heure (Lausanne):** {now:%Y-%m-%d %H:%M:%S}\n" \
          f"🔄 **Session active:** {sess}"
    await ctx.send(msg)


@bot.command(name='stats', help='Statistiques détaillées')
@check_maintenance()
async def stats(ctx):
    tbl = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    all_ = tbl.all()
    uni = len(all_)
    tot = sum(u['minutes'] for u in all_)
    avg = tot/uni if uni else 0
    # total A/B
    totA = sum(m for uid,m in classement_top10(ctx.guild.id) if uid in PARTICIPANTS_A)
    totB = sum(m for uid,m in classement_top10(ctx.guild.id) if uid in PARTICIPANTS_B)
    embed = discord.Embed(title="📊 Stats Pomodoro", color=0x33c6bb)
    embed.add_field(name="Utilisateurs uniques", value=str(uni), inline=False)
    embed.add_field(name="Temps total (min)",    value=str(tot), inline=False)
    embed.add_field(name="Moyenne/utilisateur",  value=f"{avg:.1f}", inline=False)
    embed.add_field(name="Temps total A (min)",  value=str(totA), inline=False)
    embed.add_field(name="Temps total B (min)",  value=str(totB), inline=False)
    await ctx.send(embed=embed)


@bot.command(name='leaderboard', help='Top 10 général')
@check_maintenance()
async def leaderboard(ctx):
    top = classement_top10(ctx.guild.id)
    if not top:
        return await ctx.send("🏆 Leaderboard vide.")
    embed = discord.Embed(title="🏆 Leaderboard Pomodoro", color=0x6040b1)
    for i,(uid,mins) in enumerate(top,1):
        user = await bot.fetch_user(uid)
        embed.add_field(name=f"#{i} {user}", value=f"{mins} min", inline=False)
    await ctx.send(embed=embed)


# ─── COMMANDES ADMIN ───────────────────────────────────────────────────────────
@bot.command(name='maintenance', help='Activer/désactiver maintenance')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    state = "activée" if MAINTENANCE_MODE else "désactivée"
    await ctx.send(f"🔧 Mode maintenance {state}.")


@bot.command(name='set_channel', help='Définir canal Pomodoro')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini','w') as f: config.write(f)
    global POMODORO_CHANNEL_ID; POMODORO_CHANNEL_ID = channel.id
    await ctx.send(f"✅ Canal défini sur {channel.mention}.")


@bot.command(name='set_role_A', help='Définir rôle mode A')
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global POMO_ROLE_A; POMO_ROLE_A = role.name
    await ctx.send(f"✅ Rôle A défini sur {role.mention}.")


@bot.command(name='set_role_B', help='Définir rôle mode B')
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    global POMO_ROLE_B; POMO_ROLE_B = role.name
    await ctx.send(f"✅ Rôle B défini sur {role.mention}.")


@bot.command(name='clear_stats', help='Réinitialiser toutes les stats')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    await ctx.send("🗑️ Statistiques réinitialisées.")


@bot.command(name='help', help='Affiche ce message')
async def help_cmd(ctx):
    e = discord.Embed(title=messages.HELP["title"], color=messages.HELP["color"])
    for f in messages.HELP["fields"]:
        e.add_field(name=f["name"], value=f["value"], inline=f["inline"])
    await ctx.send(embed=e)


# ─── BOUCLE POMODORO ────────────────────────────────────────────────────────────
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    if not channel or not (PARTICIPANTS_A|PARTICIPANTS_B):
        return

    # déclenchement séparé pour A et B
    for mode, parts, work, pause, role in (
        ('A', PARTICIPANTS_A, WORK_TIME_A, BREAK_TIME_A, POMO_ROLE_A),
        ('B', PARTICIPANTS_B, WORK_TIME_B, BREAK_TIME_B, POMO_ROLE_B)
    ):
        if not parts:
            continue
        SESSION_ACTIVE = True
        SESSION_PHASE  = 'work'
        SESSION_END    = datetime.now(timezone.utc) + timedelta(minutes=work)
        mention = (await ensure_role(channel.guild, role)).mention
        await channel.send(f"▶️ Début travail ({mode}, {work} min) ! {mention}")
        await asyncio.sleep(work*60)

        SESSION_PHASE = 'break'
        SESSION_END   = datetime.now(timezone.utc) + timedelta(minutes=pause)
        await channel.send(f"⏸️ Début pause ({mode}, {pause} min) ! {mention}")
        await asyncio.sleep(pause*60)

        # enregistrement du temps
        for uid in list(parts):
            ajouter_temps(uid, channel.guild.id, work)

    SESSION_ACTIVE = False


if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
