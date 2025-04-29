import os
import discord
from discord.ext import commands, tasks
import configparser
import asyncio
from enum import Enum
from tinydb import TinyDB
from database import (
    ajouter_temps, remove_participant,
    get_all_participants, add_participant,
    classement_top10
)
from keep_alive import keep_alive
import logging
from datetime import datetime, timezone, timedelta

# — CONFIG & GLOBALS —
config = configparser.ConfigParser()
config.read('settings.ini')

prefix   = config['CURRENT_SETTINGS'].get('prefix', '*')
BOT_TOKEN= os.getenv('DISCORD_TOKEN')
WORK     = int(config['CURRENT_SETTINGS']['work_time'])
BREAK    = int(config['CURRENT_SETTINGS']['break_time'])
CHAN_ID  = config['CURRENT_SETTINGS'].getint('channel_id', fallback=None)
ROLE     = config['CURRENT_SETTINGS'].get('pomodoro_role', '50-10')

SESSION_ACTIVE = False
SESSION_PHASE  = None   # 'work' ou 'break'
SESSION_END    = None

# Liste des participants en mémoire (sera rechargée au ready)
PARTICIPANTS = []

# — BOT SETUP —
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=prefix,
    help_command=None,
    intents=intents,
    case_insensitive=True    # E1: insensible à la casse
)

# — LOGGING —
logger = logging.getLogger('pomobot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
logger.addHandler(fh)

# — COLORS —
class MsgColors(Enum):
    AQUA   = 0x33c6bb
    PURPLE = 0x6040b1

# — CHECKS —
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def check_maintenance_mode():
    async def predicate(ctx):
        return True
    return commands.check(predicate)

# — UTILS —
async def get_role_mention(guild: discord.Guild) -> str:
    role = discord.utils.get(guild.roles, name=ROLE)
    if role is None:
        role = await guild.create_role(name=ROLE)
        logger.info(f"Rôle '{ROLE}' créé dans {guild.name}")
    return role.mention

# — VIEW: Join/Leave Buttons — #
class JoinLeaveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persists tant que le bot tourne

    @discord.ui.button(label="Rejoindre", style=discord.ButtonStyle.success)
    async def join_button(self, button, interaction):
        uid = interaction.user.id
        gid = interaction.guild.id
        if uid in PARTICIPANTS:
            return await interaction.response.send_message(
                "Vous êtes déjà inscrit·e.", ephemeral=True)
        PARTICIPANTS.append(uid)
        add_participant(uid, gid)
        await interaction.user.add_roles(
            discord.utils.get(interaction.guild.roles, name=ROLE))
        await interaction.response.send_message(
            "Vous avez rejoint le Pomodoro.", ephemeral=True)

    @discord.ui.button(label="Quitter", style=discord.ButtonStyle.danger)
    async def leave_button(self, button, interaction):
        uid = interaction.user.id
        gid = interaction.guild.id
        if uid not in PARTICIPANTS:
            return await interaction.response.send_message(
                "Vous n'étiez pas inscrit·e.", ephemeral=True)
        PARTICIPANTS.remove(uid)
        join_ts = remove_participant(uid, gid)
        if join_ts:
            elapsed = int((datetime.now(timezone.utc).timestamp() - join_ts) / 60)
            ajouter_temps(uid, gid, elapsed)
        await interaction.user.remove_roles(
            discord.utils.get(interaction.guild.roles, name=ROLE))
        await interaction.response.send_message(
            f"Vous avez quitté. Temps ajouté : {elapsed if join_ts else 0} min.", ephemeral=True)

# — EVENTS —
@bot.event
async def on_ready():
    logger.info(f"{bot.user} connecté.")
    # Recharger participants depuis TinyDB (A2)
    if CHAN_ID:
        chan = bot.get_channel(CHAN_ID)
        if chan:
            PARTICIPANTS.clear()
            PARTICIPANTS.extend(get_all_participants(chan.guild.id))
            # Envoyer/pinner le message de contrôle si besoin
            view = JoinLeaveView()
            msg = await chan.send(
                embed=discord.Embed(
                    title="🔔 Contrôles Pomodoro",
                    description="Cliquez sur **Rejoindre** ou **Quitter** ci-dessous.",
                    color=MsgColors.AQUA.value
                ),
                view=view
            )
            await msg.pin()
    if not pomodoro_loop.is_running():
        pomodoro_loop.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return await ctx.send(f"Commande inconnue. Tapez `{prefix}help`.")
    await ctx.send(f"Erreur : {error}")
    logger.error(error)

# — COMMANDES — #
@bot.command(name='join', help='Rejoindre le Pomodoro')  # accessible via bouton aussi
@check_maintenance_mode()
async def join_cmd(ctx):
    await ctx.send("Utilisez les boutons épinglés pour vous inscrire 😉")

@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance_mode()
async def leave_cmd(ctx):
    await ctx.send("Utilisez les boutons épinglés pour vous désinscrire 😉")

@bot.command(name='time', help='Temps restant de la session en cours')
@check_maintenance_mode()
async def time_left(ctx):
    if not SESSION_ACTIVE:
        return await ctx.send(embed=discord.Embed(
            description="Aucune session en cours.",
            color=MsgColors.RED.value
        ))
    now = datetime.now(timezone.utc)
    rem = SESSION_END - now
    m, s = divmod(max(int(rem.total_seconds()), 0), 60)
    phase = 'travail' if SESSION_PHASE=='work' else 'pause'
    embed = discord.Embed(
        title=f"🕒 Session {phase}",
        description=f"{m} min {s} sec restantes",
        color=MsgColors.PURPLE.value
    )
    await ctx.send(embed=embed)

@bot.command(name='ping', help='Vérifie la latence du bot')
async def ping(ctx):
    embed = discord.Embed(
        title="🏓 Pong !",
        description=f"Latence : {round(bot.latency*1000)} ms",
        color=MsgColors.AQUA.value
    )
    await ctx.send(embed=embed)

@bot.command(name='stats', help='Voir statistiques d’utilisation')
@check_maintenance_mode()
async def stats(ctx):
    gid = ctx.guild.id
    table = TinyDB('leaderboard.json').table(str(gid))
    users = table.all()
    total = sum(u['minutes'] for u in users)
    count = len(users)
    embed = discord.Embed(
        title="📊 Stats Pomodoro",
        color=MsgColors.AQUA.value
    )
    embed.add_field(name="Utilisateurs uniques", value=str(count), inline=False)
    embed.add_field(name="Temps total (min)",      value=str(total), inline=False)
    if count:
        embed.add_field(name="Moyenne par user",  value=f"{total/count:.1f} min", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', help='Afficher le top des meilleurs révisions')
@is_admin()
@check_maintenance_mode()
async def leaderboard(ctx):
    top10 = classement_top10(ctx.guild.id)
    embed = discord.Embed(
        title="🏆 Leaderboard Pomodoro",
        color=MsgColors.PURPLE.value
    )
    if not top10:
        embed.description = "Aucun utilisateur pour l'instant."
    else:
        desc = ''.join(
            f"**#{i}** {await bot.fetch_user(uid)} : {mins} min\n"
            for i,(uid,mins) in enumerate(top10, start=1)
        )
        embed.description = desc
    await ctx.send(embed=embed)

@bot.command(name='clear_stats', help='Vider toutes les stats (admin)')
@is_admin()
async def clear_stats(ctx):
    TinyDB('leaderboard.json').purge_tables()
    await ctx.send("✅ Toutes les statistiques ont été réinitialisées.")

@bot.command(name='set_channel', help='Choisir canal Pomodoro (admin)')
@is_admin()
async def set_channel(ctx, channel: discord.TextChannel):
    config['CURRENT_SETTINGS']['channel_id'] = str(channel.id)
    with open('settings.ini','w') as f: config.write(f)
    await ctx.send(f"Canal Pomodoro défini sur {channel.mention}")

@bot.command(name='set_role', help='Choisir rôle Pomodoro (admin)')
@is_admin()
async def set_role(ctx, role: discord.Role):
    config['CURRENT_SETTINGS']['pomodoro_role'] = role.name
    with open('settings.ini','w') as f: config.write(f)
    await ctx.send(f"Rôle Pomodoro défini sur {role.name}")

@bot.command(name='help', help='Affiche la liste des commandes')
async def help_cmd(ctx):
    e = discord.Embed(title="🛠️ Commandes Pomodoro", color=MsgColors.PURPLE.value)
    e.add_field(
        name="Étudiant",
        value=(
            f"`{prefix}time` – temps restant\n"
            f"`{prefix}stats` – vos stats\n"
            f"`{prefix}help` – ce message"
        ), inline=False
    )
    e.add_field(
        name="Admin",
        value=(
            f"`{prefix}leaderboard` – top 10\n"
            f"`{prefix}clear_stats` – vider stats\n"
            f"`{prefix}set_channel` – définir canal\n"
            f"`{prefix}set_role` – définir rôle\n"
        ), inline=False
    )
    await ctx.send(embed=e)

# — POMODORO LOOP — #
@tasks.loop(minutes=1)
async def pomodoro_loop():
    global SESSION_ACTIVE, SESSION_PHASE, SESSION_END
    # Si pas de participants, on ne spamme pas
    if not PARTICIPANTS:
        return

    channel = bot.get_channel(CHAN_ID)
    if not channel:
        return

    # Démarrer travail
    SESSION_ACTIVE = True
    SESSION_PHASE = 'work'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=WORK)
    mention = await get_role_mention(channel.guild)
    await channel.send(f"Début travail ({WORK} min) ! {mention}")
    await asyncio.sleep(WORK*60)

    # Démarrer pause
    SESSION_PHASE = 'break'
    SESSION_END = datetime.now(timezone.utc) + timedelta(minutes=BREAK)
    mention = await get_role_mention(channel.guild)
    await channel.send(f"Début pause ({BREAK} min) ! {mention}")
    await asyncio.sleep(BREAK*60)

    # Fin session : on vide seulement le flag SESSION_ACTIVE
    SESSION_ACTIVE = False

# — MAIN — #
if __name__ == '__main__':
    keep_alive()
    bot.run(BOT_TOKEN)
