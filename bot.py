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

bot = commands.Bot(command_prefix=COMMAND_PREFIX,
                   intents=intents,
                   help_command=None)

# Variables maintenance et fichier logs
maintenance_mode = False
if not os.path.exists("logs.txt"):
    with open("logs.txt", "w") as f:
        f.write("")

def log(message):
    print(message)
    with open("logs.txt", "a") as f:
        f.write(message + "\n")

# Couleurs embeds
class MsgColors(Enum):
    AQUA = 0x33c6bb
    YELLOW = 0xFFD966
    RED = 0xEA3546
    PURPLE = 0x6040b1

# Evenement prêt
@bot.event
async def on_ready():
    log(f"{bot.user} est connecté !")
    await setup_roles(bot)
    bot.loop.create_task(start_timers())

# Lancer les timers
async def start_timers():
    timer_A = TimerSession('50-10', 50, 10)
    timer_B = TimerSession('25-5', 25, 5)

    await asyncio.gather(
        timer_A.run(bot, POMODORO_CHANNEL_ID,
                    lambda name: get_participants(name)),
        timer_B.run(bot, POMODORO_CHANNEL_ID,
                    lambda name: get_participants(name)))

# Fonction pour récupérer les participants
def get_participants(name):
    mode = '50-10' if name == '50-10' else '25-5'
    return sessions[mode]

# Protection maintenance
def maintenance_check():
    async def predicate(ctx):
        if maintenance_mode and not any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles):
            await ctx.send("❌ Le bot est actuellement en maintenance. Merci de patienter.")
            return False
        return True
    return commands.check(predicate)

# ----------------- Commandes Utilisateurs -----------------

@bot.command(name='join', help='Rejoindre une session Pomodoro (A: 50-10 [ou] B: 25-5)')
@maintenance_check()
async def join(ctx, mode: str):
    await join_session(bot, ctx, mode)
    log(f"{ctx.author.name} a rejoint {mode.upper()}")

@bot.command(name='leave', help='Quitter une session Pomodoro')
@maintenance_check()
async def leave(ctx):
    await leave_session(bot, ctx)
    log(f"{ctx.author.name} a quitté sa session")

@bot.command(name='time', help='Afficher le temps restant dans le cycle actuel')
@maintenance_check()
async def time(ctx):
    await ctx.send("Temps restant A:  (simulé)\nTemps restant B: (simulé)")

@bot.command(name='status', help='Voir l\'état actuel des cycles')
@maintenance_check()
async def status(ctx):
    await ctx.send("Status A: Travail\nStatus B: Pause")

@bot.command(name='leaderboard', help='Voir les classements')
@maintenance_check()
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

    desc += f"\n**Ton Temps Perso :**\n50-10 ➔ {user_times.get('50-10',0)} min\n25-5 ➔ {user_times.get('25-5',0)} min"

    embed = discord.Embed(title="Classements Pomodoro 📚",
                          description=desc,
                          color=MsgColors.PURPLE.value)
    await ctx.send(embed=embed)

@bot.command(name='help', help='Affiche les commandes disponibles')
async def help_command(ctx):
    desc = f"Préfixe : `{COMMAND_PREFIX}`\n\n"
    desc += "**Commandes Utilisateur :**\n"
    for command in bot.commands:
        if command.name not in ['maintenance', 'reloadtimers', 'adminping', 'helpadmin', 'pingtest']:
            desc += f"`{command.name}` : {command.help}\n"
    desc += "\n**Commandes Admin :**\nTapez `*helpadmin` pour voir les commandes admin."
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
    desc += "`pingtest` : Ping de test interne (caché)."
    embed = discord.Embed(title='Commandes Admin', description=desc, color=MsgColors.RED.value)
    await ctx.send(embed=embed)

@bot.command(name='maintenance', help='Basculer en mode maintenance')
@is_admin()
async def maintenance(ctx):
    global maintenance_mode
    maintenance_mode = not maintenance_mode
    status = "🛠️ Maintenance activée" if maintenance_mode else "✅ Maintenance désactivée"
    await ctx.send(status)
    log(f"Maintenance modifiée: {status}")

@bot.command(name='reloadtimers', help='Recharger les timers')
@is_admin()
async def reloadtimers(ctx):
    await ctx.send("Timers rechargés !")
    log(f"Timers rechargés par {ctx.author.name}")

@bot.command(name='adminping', help='Tester un ping admin')
@is_admin()
async def adminping(ctx):
    await ctx.send("Admin ping réussi !")

@bot.command(name='pingtest', help='(Caché) Test ping interne')
@is_admin()
async def pingtest(ctx):
    await ctx.send("Ping Test OK ✅")

# ----------------- Lancer le Bot -----------------
if __name__ == '__main__':
    bot.run(TOKEN)
