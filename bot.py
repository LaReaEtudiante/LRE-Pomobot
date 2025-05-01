# bot.py

import os
import discord
from discord.ext import commands, tasks
import configparser
import logging
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
import messages

# ─── CONFIGURATION & CONSTANTES ────────────────────────────────────────────────
TZ = ZoneInfo('Europe/Zurich')
cfg = configparser.ConfigParser()
cfg.read('settings.ini')

WORK_TIME_A  = cfg['CURRENT_SETTINGS'].getint('work_time_A',   fallback=50)
BREAK_TIME_A = cfg['CURRENT_SETTINGS'].getint('break_time_A',  fallback=10)
POMO_ROLE_A  = cfg['CURRENT_SETTINGS'].get('pomodoro_role_A', fallback='50-10')
WORK_TIME_B  = cfg['CURRENT_SETTINGS'].getint('work_time_B',   fallback=25)
BREAK_TIME_B = cfg['CURRENT_SETTINGS'].getint('break_time_B',  fallback=5)
POMO_ROLE_B  = cfg['CURRENT_SETTINGS'].get('pomodoro_role_B', fallback='25-5')

POMODORO_CHANNEL_ID = cfg['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
PREFIX             = cfg['CURRENT_SETTINGS'].get('prefix','*')
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
logger = logging.getLogger('pomobot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomobot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# ─── ÉTAT ─────────────────────────────────────────────────────────────────────
PARTICIPANTS_A = set()
PARTICIPANTS_B = set()

# ─── UTILITAIRES ───────────────────────────────────────────────────────────────
def is_admin():
    async def p(ctx): return ctx.author.guild_permissions.administrator
    return commands.check(p)

def check_maintenance():
    async def p(ctx):
        if MAINTENANCE_MODE and ctx.command.name!='maintenance':
            raise commands.CommandError("Bot en mode maintenance.")
        return True
    return commands.check(p)

async def ensure_role(guild: discord.Guild, name: str):
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name)
        logger.info(f"Rôle '{name}' créé dans '{guild.name}'")
    return role

def compute_phase_and_remaining(mode: str):
    now = datetime.now(TZ)
    m, s = now.minute, now.second
    if mode=='A':
        if m<50 or (m==50 and s==0): phase, tgt= 'Travail',50
        else:                          phase, tgt= 'Pause',60
    else:
        if   m<25 or (m==25 and s==0): phase, tgt= 'Travail',25
        elif m<30 or (m==30 and s==0): phase, tgt= 'Pause',30
        elif m<55 or (m==55 and s==0): phase, tgt= 'Travail',55
        else:                          phase, tgt= 'Pause',60
    secs = max((tgt-m-1)*60 + (60-s),0)
    return phase, secs

# ─── EVENTS ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global MAINTENANCE_MODE
    logger.info(f"{bot.user} connecté.")
    for g in bot.guilds:
        for uid, mode in get_all_participants(g.id):
            (PARTICIPANTS_A if mode=='A' else PARTICIPANTS_B).add(uid)
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        txt = messages.TEXT["command_not_found"].format(prefix=PREFIX)
    elif isinstance(error, commands.CommandError) and str(error)=="Bot en mode maintenance.":
        txt = messages.TEXT["maintenance_active"]
    elif isinstance(error, commands.MissingRequiredArgument):
        txt = messages.TEXT["missing_argument"]
    elif isinstance(error, commands.CheckFailure):
        txt = messages.TEXT["permission_denied"]
    else:
        txt = messages.TEXT["unexpected_error"].format(error=str(error))
    await ctx.send(txt)

# ─── COMMANDES ÉTUDIANT ───────────────────────────────────────────────────────
@bot.command(name='joinA', help='Rejoindre méthode A (50-10)')
@check_maintenance()
async def joinA(ctx):
    u=ctx.author
    if u.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(messages.TEXT["already_joined"])
    PARTICIPANTS_A.add(u.id)
    add_participant(u.id, ctx.guild.id,'A')
    await u.add_roles(await ensure_role(ctx.guild,POMO_ROLE_A))
    await ctx.send(messages.TEXT["join_A"].format(user_mention=u.mention))

@bot.command(name='joinB', help='Rejoindre méthode B (25-5)')
@check_maintenance()
async def joinB(ctx):
    u=ctx.author
    if u.id in PARTICIPANTS_A|PARTICIPANTS_B:
        return await ctx.send(messages.TEXT["already_joined"])
    PARTICIPANTS_B.add(u.id)
    add_participant(u.id, ctx.guild.id,'B')
    await u.add_roles(await ensure_role(ctx.guild,POMO_ROLE_B))
    await ctx.send(messages.TEXT["join_B"].format(user_mention=u.mention))

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance()
async def leave(ctx):
    u=ctx.author
    join_ts,mode = remove_participant(u.id,ctx.guild.id)
    if join_ts is None:
        return await ctx.send(messages.TEXT["not_registered"])
    mins = max(int((datetime.now(timezone.utc).timestamp()-join_ts)//60),1)
    ajouter_temps(u.id,ctx.guild.id,mins)
    role_nm = POMO_ROLE_A if mode=='A' else POMO_ROLE_B
    rl = discord.utils.get(ctx.guild.roles,name=role_nm)
    if rl: await u.remove_roles(rl)
    await ctx.send(messages.TEXT["leave"].format(user_mention=u.mention, minutes=mins))

@bot.command(name='time', help='Temps restant session')
@check_maintenance()
async def time_cmd(ctx):
    pA, sA = compute_phase_and_remaining('A')
    pB, sB = compute_phase_and_remaining('B')
    e=discord.Embed(title="⏱️ Temps restant Pomodoro", color=messages.MsgColors.AQUA.value)
    e.add_field(name=f"Mode A ({POMO_ROLE_A})", value=f"{pA} – {sA//60}m{sA%60}s", inline=False)
    e.add_field(name=f"Mode B ({POMO_ROLE_B})", value=f"{pB} – {sB//60}m{sB%60}s", inline=False)
    await ctx.send(embed=e)

# ─── BOUCLE AUTOMATIQUE ─────────────────────────────────────────────────────────
@tasks.loop(seconds=30)
async def pomodoro_loop():
    ch = bot.get_channel(POMODORO_CHANNEL_ID)
    if not ch or datetime.now(TZ).second>2:
        return
    for mode, parts, work, brk, rn in (
        ('A',PARTICIPANTS_A,WORK_TIME_A,BREAK_TIME_A,POMO_ROLE_A),
        ('B',PARTICIPANTS_B,WORK_TIME_B,BREAK_TIME_B,POMO_ROLE_B)
    ):
        if not parts: continue
        ph,_=compute_phase_and_remaining(mode)
        km = {0:'Travail',50:'Pause'} if mode=='A' else {0:'Travail',25:'Pause',30:'Travail',55:'Pause'}
        m = datetime.now(TZ).minute
        if m in km and km[m]==ph:
            mention=(await ensure_role(ch.guild,rn)).mention
            emoji="▶️" if ph=='Travail' else "⏸️"
            duration = work if ph=='Travail' else brk
            await ch.send(f"{emoji} Début {ph.lower()} ({mode}, {duration} min) ! {mention}")

# ─── STATUS / STATS / LEADERBOARD ─────────────────────────────────────────────
@bot.command(name='status', help='État du bot')
async def status(ctx):
    lat = round(bot.latency*1000)
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    pA,sA = compute_phase_and_remaining('A')
    pB,sB = compute_phase_and_remaining('B')
    e=discord.Embed(title=messages.STATUS["title"], color=messages.STATUS["color"])
    for f in messages.STATUS["fields"]:
        v=f["value_template"].format(
            latency=lat, local_time=now,
            mode_A=pA, remaining_A=f"{sA//60}m{sA%60}s",
            mode_B=pB, remaining_B=f"{sB//60}m{sB%60}s"
        )
        e.add_field(name=f["name"], value=v, inline=f["inline"])
    await ctx.send(embed=e)

@bot.command(name='stats', help='Vos stats')
@check_maintenance()
async def stats(ctx):
    tbl=TinyDB('leaderboard.json').table(str(ctx.guild.id))
    recs=tbl.all(); u=len(recs); tot=sum(r['minutes'] for r in recs)
    avg=(tot/u) if u else 0
    e=discord.Embed(title=messages.STATS["title"], color=messages.STATS["color"])
    for f in messages.STATS["fields"]:
        v=f["value_template"].format(unique_users=u, total_minutes=tot, average_minutes=avg)
        e.add_field(name=f["name"], value=v, inline=f["inline"])
    await ctx.send(embed=e)

@bot.command(name='leaderboard', help='Top 5 général')
@check_maintenance()
async def leaderboard(ctx):
    top=classement_top10(ctx.guild.id)[:5]
    e=discord.Embed(title=messages.LEADERBOARD["title"], color=messages.LEADERBOARD["color"])
    if not top:
        e.description="Aucun utilisateur."
    else:
        for i,(uid,m) in enumerate(top,1):
            u=await bot.fetch_user(uid)
            e.add_field(
                name=messages.LEADERBOARD["entry_template"]["name_template"].format(rank=i,username=u.name),
                value=messages.LEADERBOARD["entry_template"]["value_template"].format(minutes=m),
                inline=False
            )
    await ctx.send(embed=e)

# ─── COMMANDES ADMIN ──────────────────────────────────────────────────────────
@bot.command(name='maintenance', help='Mode maintenance on/off')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE=not MAINTENANCE_MODE
    st="activé" if MAINTENANCE_MODE else "désactivé"
    await ctx.send(messages.TEXT["maintenance_toggle"].format(state=st))

@bot.command(name='set_channel', help='Définir canal (admin)')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    cfg['CURRENT_SETTINGS']['channel_id']=str(channel.id)
    with open('settings.ini','w') as f: cfg.write(f)
    global POMODORO_CHANNEL_ID; POMODORO_CHANNEL_ID=channel.id
    await ctx.send(messages.TEXT["set_channel"].format(channel_mention=channel.mention))

@bot.command(name='set_role_A', help='Définir rôle A (admin)')
@is_admin()
async def set_role_A(ctx, role: discord.Role):
    cfg['CURRENT_SETTINGS']['pomodoro_role_A']=role.name
    with open('settings.ini','w') as f: cfg.write(f)
    global POMO_ROLE_A; POMO_ROLE_A=role.name
    await ctx.send(messages.TEXT["set_role_A"].format(role_mention=role.mention))

@bot.command(name='set_role_B', help='Définir rôle B (admin)')
@is_admin()
async def set_role_B(ctx, role: discord.Role):
    cfg['CURRENT_SETTINGS']['pomodoro_role_B']=role.name
    with open('settings.ini','w') as f: cfg.write(f)
    global POMO_ROLE_B; POMO_ROLE_B=role.name
    await ctx.send(messages.TEXT["set_role_B"].format(role_mention=role.mention))

@bot.command(name='clear_stats', help='Réinitialiser stats (admin)')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').drop_table(str(ctx.guild.id))
    await ctx.send(messages.TEXT["clear_stats"])

@bot.command(name='help', help='Afficher ce message')
async def help_cmd(ctx):
    e=discord.Embed(title=messages.HELP["title"], color=messages.HELP["color"])
    for f in messages.HELP["fields"]:
        e.add_field(name=f["name"], value=f["value"], inline=f["inline"])
    await ctx.send(embed=e)

# ─── LANCEMENT ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    bot.run(os.getenv('DISCORD_TOKEN'))
