import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
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
                   help_command=None,
                   case_insensitive=True)

# Variables globales
maintenance_mode = False


# Couleurs embeds
class MsgColors(Enum):
    AQUA = 0x33c6bb
    YELLOW = 0xFFD966
    RED = 0xEA3546
    PURPLE = 0x6040b1


# Maintenance check
def maintenance_check():

    async def predicate(ctx):
        if maintenance_mode and not any(role.id == ADMIN_ROLE_ID
                                        for role in ctx.author.roles):
            embed = discord.Embed(
                title="Maintenance 🛠️",
                description=
                "❌ Le bot est actuellement en maintenance. Merci de patienter.",
                color=MsgColors.RED.value)
            await ctx.send(embed=embed)
            raise commands.CheckFailure("Maintenance active.")
        return True

    return commands.check(predicate)


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
        timer_A.run(bot, POMODORO_CHANNEL_ID,
                    lambda name: get_participants(name)),
        timer_B.run(bot, POMODORO_CHANNEL_ID,
                    lambda name: get_participants(name)))


# Participants
def get_participants(name):
    mode = '50-10' if name == '50-10' else '25-5'
    return sessions[mode]


# ----------------- Commandes Utilisateurs -----------------
@bot.command(name='join',
             help='Rejoindre une session Pomodoro (A: 50-10 [ou] B: 25-5)')
@maintenance_check()
async def join(ctx, mode: str):
    mode = mode.lower()
    if mode in ['a', '50-10']:
        await join_session(bot, ctx, '50-10')
    elif mode in ['b', '25-5']:
        await join_session(bot, ctx, '25-5')
    else:
        embed = discord.Embed(
            title="Erreur",
            description="❌ Mode invalide. Utilisez 'A' (50-10) ou 'B' (25-5)",
            color=MsgColors.RED.value)
        await ctx.send(embed=embed)


@bot.command(name='leave', help='Quitter une session Pomodoro')
@maintenance_check()
async def leave(ctx):
    await leave_session(bot, ctx)


@bot.command(name='time', help='Afficher le temps restant pour chaque mode')
@maintenance_check()
async def time(ctx):
    desc = ""
    for session_name, timer in TimerSession.instances.items():
        desc += f"**{session_name}** ➔ {timer.remaining_minutes()} minutes restantes ({'Travail' if timer.is_working() else 'Pause'})\n"
    embed = discord.Embed(title="Temps Restant ⏳",
                          description=desc,
                          color=MsgColors.AQUA.value)
    await ctx.send(embed=embed)


@bot.command(name='status', help='Voir l\'état actuel des cycles')
@maintenance_check()
async def status(ctx):
    desc = ""
    for session_name, timer in TimerSession.instances.items():
        desc += f"**{session_name}** ➔ {'En Travail 📝' if timer.is_working() else 'En Pause ☕'}\n"
    embed = discord.Embed(title="État des Cycles Pomodoro 📚",
                          description=desc,
                          color=MsgColors.AQUA.value)
    await ctx.send(embed=embed)


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

    desc += f"\n**Ton Temps Perso :**\n50-10 ➔ {user_times.get('50-10', 0)} min\n25-5 ➔ {user_times.get('25-5', 0)} min"

    embed = discord.Embed(title="Classements Pomodoro 📚",
                          description=desc,
                          color=MsgColors.PURPLE.value)
    await ctx.send(embed=embed)


@bot.command(name='help', help='Affiche les commandes disponibles')
async def help_command(ctx):
    desc = f"Préfixe : `{COMMAND_PREFIX}`\n\n"
    desc += "**Commandes Utilisateur :**\n"
    for command in bot.commands:
        if command.name not in [
                'maintenance', 'reloadtimers', 'adminping', 'helpadmin'
        ]:
            desc += f"`{command.name}` : {command.help}\n"
    desc += "\n**Commandes Admin :**\nTapez `*helpadmin` pour voir les commandes admin."
    embed = discord.Embed(title='Commandes du Bot',
                          description=desc,
                          color=MsgColors.PURPLE.value)
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
    desc += "`adminping` : Tester un ping admin."
    embed = discord.Embed(title='Commandes Admin',
                          description=desc,
                          color=MsgColors.RED.value)
    await ctx.send(embed=embed)


@bot.command(name='maintenance', help='Basculer en mode maintenance')
@is_admin()
async def maintenance(ctx):
    global maintenance_mode
    maintenance_mode = not maintenance_mode
    msg = "Maintenance activée 🛠️" if maintenance_mode else "Maintenance désactivée ✅"
    embed = discord.Embed(title="Maintenance",
                          description=msg,
                          color=MsgColors.RED.value)
    await ctx.send(embed=embed)


@bot.command(name='reloadtimers', help='Recharger les timers')
@is_admin()
async def reloadtimers(ctx):
    await ctx.send("Timers rechargés !")


@bot.command(name='adminping', help='Tester un ping admin')
@is_admin()
async def adminping(ctx):
    embed = discord.Embed(title="Admin Ping",
                          description="✅ Admin ping réussi !",
                          color=MsgColors.AQUA.value)
    await ctx.send(embed=embed)


# ----------------- Lancer le Bot -----------------
if __name__ == '__main__':
    bot.run(TOKEN)
