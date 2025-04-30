# bot.py

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
    ajouter_temps,
    recuperer_temps,
    classement_top10,
    add_participant,
    remove_participant,
    get_all_participants
)
from keep_alive import keep_alive

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
SESSION_MODE   = None        # 'A' ou 'B'
SESSION_PHASE  = None        # 'work' ou 'break'
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
    # restaurer les participants en base
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
    embed = discord.Embed(
        title=err.get("title",""),
        description=err.get("description", err.get("description_template","")).format(prefix=PREFIX, error=str(error)),
        color=err["color"]
    )
    await ctx.send(embed=embed)


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
        role_name = POMO_ROLE_A
    else:
        PARTICIPANTS_B.discard(user.id)
        role_name = POMO_ROLE_B
    role_obj = discord.utils.get(ctx.guild.roles, name=role_name)
    if role_obj:
        await user.remove_roles(role_obj)
    tpl = messages.LEAVE
    await ctx.send(f"✅ {tpl['description_template'].format(user_mention=user.mention, minutes=mins)}")


@bot.command(name='time', help='Temps restants des deux modes')
@check_maintenance()
async def time_left(ctx):
    """
    Affiche, pour A et pour B, le temps restant de la session en cours (work/pause),
    ou 'aucune session' si inactif.
    """
    e = discord.Embed(title="⏱️ Temps restants", color=messages.MsgColors.AQUA.value)
    now = datetime.now(timezone.utc)
    for mode_label, parts in (('A', PARTICIPANTS_A), ('B', PARTICIPANTS_B)):
        if SESSION_ACTIVE and SESSION_MODE==mode_label:
            rem = max(int((SESSION_END - now).total_seconds()),0)
            m, s = divmod(rem, 60)
            phase = SESSION_PHASE
            e.add_field(
                name=f"Mode {mode_label}",
                value=f"{phase} : {m} min {s} sec restantes",
                inline=False
            )
        else:
            e.add_field(name=f"Mode {mode_label}", value="aucune session", inline=False)
    await ctx.send(embed=e)


# ─── COMMANDE STATUS ─────────────────────────────────────────────────────────
@bot.command(name='status', help='État complet du bot')
async def status(ctx):
    """
    Embed avec latence, heure locale, et statut des sessions A & B.
    """
    latency = round(bot.latency*1000)
    now_local = datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Zurich'))
    e = discord.Embed(title="🔍 État du bot", color=messages.MsgColors.PURPLE.value)
    e.add_field(name="🏷️ Latence", value=f"{latency} ms", inline=True)
    e.add_field(name="🕒 Heure (Lausanne)", value=now_local.strftime("%Y-%m-%d %H:%M:%S"), inline=True)

    now = datetime.now(timezone.utc)
    for mode_label in ('A','B'):
        if SESSION_ACTIVE and SESSION_MODE==mode_label:
            rem = max(int((SESSION_END - now).total_seconds()),0)
            m = rem//60
            e.add_field(name=f"🔄 Session {mode_label}", value=f"{SESSION_PHASE} ({m} min restantes)", inline=False)
        else:
            e.add_field(name=f"🔄 Session {mode_label}", value="aucune", inline=False)

    await ctx.send(embed=e)


# ─── STATS & LEADERBOARD ───────────────────────────────────────────────────────
@bot.command(name='stats', help='Statistiques détaillées')
@check_maintenance()
async def stats(ctx):
    """
    Embed avec :
     - utilisateurs uniques
     - temps total
     - moyenne
     - total A
     - total B
    """
    tbl = TinyDB('leaderboard.json').table(str(ctx.guild.id))
    all_   = tbl.all()
    unique = len(all_)
    total  = sum(u['minutes'] for u in all_)
    avg    = (total/unique) if unique else 0

    # totaux par mode
    totA = sum(m for uid,m in all_ if uid in PARTICIPANTS_A)
    totB = sum(m for uid,m in all_ if uid in PARTICIPANTS_B)

    e = discord.Embed(title="📊 Stats Pomodoro", color=messages.MsgColors.AQUA.value)
    e.add_field(name="Utilisateurs uniques", value=str(unique), inline=False)
    e.add_field(name="Temps total (min)",    value=str(total),  inline=False)
    e.add_field(name="Moyenne/utilisateur",  value=f"{avg:.1f}", inline=False)
    e.add_field(name="Temps total A (min)",  value=str(totA),   inline=False)
    e.add_field(name="Temps total B (min)",  value=str(totB),   inline=False)
    await ctx.send(embed=e)


@bot.command(name='leaderboard', help='Top 10 général')
@check_maintenance()
async def leaderboard(ctx):
    top = classement_top10(ctx.guild.id)
    if not top:
        return await ctx.send("🏆 Leaderboard vide.")
    e = discord.Embed(title="🏆 Leaderboard Pomodoro", color=messages.MsgColors.PURPLE.value)
    for i, (uid, mins) in enumerate(top, start=1):
        user = await bot.fetch_user(uid)
        e.add_field(name=f"#{i} {user}", value=f"{mins} min", inline=False)
    await ctx.send(embed=e)


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
    with open('settings.ini','w') as f:
        config.write(f)
    global POMODORO_CHANNEL_ID
    POMODORO_CHANNEL_ID = channel.id
    await ctx.send(f"✅ Canal défini sur {channel.mention}.")


@bot.command(name='set_role_A', help='Définir rôle mode A')
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_A'] = role.name
    with open('settings.ini','w') as f:
        config.write(f)
    global POMO_ROLE_A
    POMO_ROLE_A = role.name
    await ctx.send(f"✅ Rôle A défini sur {role.mention}.")


@bot.command(name='set_role_B', help='Définir rôle mode B')
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role_B'] = role.name
    with open('settings.ini','w') as f:
        config.write(f)
    global POMO_ROLE_B
    POMO_ROLE_B = role.name
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
    global SESSION_ACTIVE, SESSION_MODE, SESSION_PHASE, SESSION_END

    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    if not channel or not (PARTICIPANTS_A|PARTICIPANTS_B):
        return

    for mode, parts, work, pause, role_name in (
        ('A', PARTICIPANTS_A, WORK_TIME_A, BREAK_TIME_A, POMO_ROLE_A),
        ('B', PARTICIPANTS_B, WORK_TIME_B, BREAK_TIME_B, POMO_ROLE_B)
    ):
        if not parts:
            continue

        SESSION_ACTIVE = True
        SESSION_MODE   = mode
        SESSION_PHASE  = 'work'
        SESSION_END    = datetime.now(timezone.utc) + timedelta(minutes=work)
        mention = (await ensure_role(channel.guild, role_name)).mention
        await channel.send(f"▶️ Début travail ({mode}, {work} min) ! {mention}")
        await asyncio.sleep(work * 60)

        SESSION_PHASE = 'break'
        SESSION_END   = datetime.now(timezone.utc) + timedelta(minutes=pause)
        await channel.send(f"⏸️ Début pause ({mode}, {pause} min) ! {mention}")
        await asyncio.sleep(pause * 60)

        for uid in list(parts):
            ajouter_temps(uid, channel.guild.id, work)

    SESSION_ACTIVE = False
    SESSION_MODE   = None


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))
