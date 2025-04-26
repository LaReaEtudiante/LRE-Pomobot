# imports
import os
import discord
from dotenv import load_dotenv
from discord.ext import commands
import asyncio
from enum import Enum
from database import save_time, get_user_times, get_leaderboard, get_global_leaderboard
from role_manager import setup_roles
from session_manager import join_session, leave_session, sessions
from timer import TimerSession
from keep_alive import keep_alive

# constantes
ADMIN_ROLE_ID = 1364921809870524436
POMODORO_CHANNEL_ID = 1365678171671892018
COMMAND_PREFIX = '*'
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

# Couleurs embeds
class MsgColors(Enum):
    AQUA = 0x33c6bb
    YELLOW = 0xFFD966
    RED = 0xEA3546
    PURPLE = 0x6040b1

# Evenement prêt
@bot.event
async def on_ready():
    print(f"{bot.user} est connecté !")
    await setup_roles(bot)
    bot.loop.create_task(start_timers())

# Lancer les timers
async def start_timers():
    timer_A = TimerSession('50-10', 50, 10)
    timer_B = TimerSession('25-5', 25, 5)

    await asyncio.gather(
        timer_A.run(bot, POMODORO_CHANNEL_ID, lambda name: get_participants(name)),
        timer_B.run(bot, POMODORO_CHANNEL_ID, lambda name: get_participants(name))
    )

# Fonction pour récupérer les participants
def get_participants(name):
    mode = '50-10' if name == '50-10' else '25-5'
    return sessions[mode]

# ----------------- Commandes Utilisateurs -----------------
@bot.command(name='join', help='Rejoindre une session Pomodoro (A ou B)')
async def join(ctx, mode: str):
    await join_session(bot, ctx, mode)

@bot.command(name='leave', help='Quitter une session Pomodoro')
async def leave(ctx):
    await leave_session(bot, ctx)

@bot.command(name='time', help='Afficher le temps restant dans le cycle actuel')
async def time(ctx):
    await ctx.send("Temps restant : (simulé)")

@bot.command(name='status', help='Voir l\'état actuel des cycles')
async def status(ctx):
    await ctx.send("Status actuel : (simulé)")

@bot.command(name='pingtest', help='Vérifie que le bot fonctionne et affiche la latence')
async def pingtest(ctx):
    latency = round(bot.latency * 1000)  # Latence en millisecondes
    await ctx.send(f"🏓 Pong ! Latence du bot : `{latency}ms`")

@bot.command(name='leaderboard', help='Voir les classements')
async def leaderboard(ctx):
    top_global = get_global_leaderboard()
    top_A = get_leaderboard('50-10')
    top_B = get_leaderboard('25-5')
    user_times = get_user_times(ctx.author.id)

    desc = "**🏆 Classement Général**\n"
    for i, (uid, minutes) in enumerate(top_global, start=1):
        user = await bot.fetch_user(uid)
        desc += f"**#{i}** {user.name} : {minutes} min\n"

    desc += "\n**📚 Mode A (50-10)**\n"
    for i, (uid, minutes) in enumerate(top_A, start=1):
        user = await bot.fetch_user(uid)
        desc += f"**#{i}** {user.name} : {minutes} min\n"

    desc += "\n**📖 Mode B (25-5)**\n"
    for i, (uid, minutes) in enumerate(top_B, start=1):
        user = await bot.fetch_user(uid)
        desc += f"**#{i}** {user.name} : {minutes} min\n"

    desc += f"\n**Ton Temps Perso :**\n50-10 ➔ {user_times.get('50-10', 0)} min\n25-5 ➔ {user_times.get('25-5', 0)} min"

    embed = discord.Embed(title="Classements Pomodoro 📚", description=desc, color=MsgColors.PURPLE.value)
    await ctx.send(embed=embed)

@bot.command(name='help', help='Affiche les commandes disponibles')
async def help_command(ctx):
    desc = f"Préfixe : `{COMMAND_PREFIX}`\n\n"
    desc += "**Commandes Utilisateur :**\n"
    for command in bot.commands:
        if command.name not in ['maintenance', 'reloadtimers', 'adminping', 'helpadmin', 'testping']:
            desc += f"`{command.name}` : {command.help}\n"
    desc += "\n**Commandes Admin :**\nTapez `⭐ helpadmin` pour voir les commandes admin."
    embed = discord.Embed(title='Commandes du Bot', description=desc, color=MsgColors.PURPLE.value)
    await ctx.send(embed=embed)

# ----------------- Commandes Admin -----------------
def is_admin():
    async def predicate(ctx):
        return any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles)
    return commands.check(predicate)

@bot.command(name='helpadmin', help='Affiche les commandes admin')
@is_admin()
async def helpadmin(ctx):
    desc = "**Commandes Admin :**\n"
    desc += "`maintenance` : Activer/désactiver le mode maintenance.\n"
    desc += "`reloadtimers` : Recharger les minuteurs.\n"
    desc += "`adminping` : Tester un ping admin.\n"
    desc += "`testping` : Tester un ping général."
    embed = discord.Embed(title='Commandes Admin', description=desc, color=MsgColors.RED.value)
    await ctx.send(embed=embed)

@bot.command(name='maintenance', help='Basculer en mode maintenance')
@is_admin()
async def maintenance(ctx):
    await ctx.send(f"{ctx.author.mention} a activé/désactivé le mode maintenance !")

@bot.command(name='reloadtimers', help='Recharger les timers')
@is_admin()
async def reloadtimers(ctx):
    await ctx.send("Timers rechargés !")

@bot.command(name='adminping', help='Tester un ping admin')
@is_admin()
async def adminping(ctx):
    await ctx.send("Admin ping réussi !")

@bot.command(name='testping', help='Tester un ping général')
async def testping(ctx):
    await ctx.send("Test ping réussi !")

# ----------------- Lancer le Bot -----------------
if __name__ == '__main__':
    keep_alive()
    bot.run(TOKEN)
