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

ADMIN_ROLE_ID = 1364921809870524436
POMODORO_CHANNEL_ID = 1365678171671892018
COMMAND_PREFIX = '*'
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX,
                   intents=intents,
                   help_command=None)

maintenance_mode = False


class MsgColors(Enum):
    AQUA = 0x33c6bb
    YELLOW = 0xFFD966
    RED = 0xEA3546
    PURPLE = 0x6040b1


@bot.event
async def on_ready():
    print(f"{bot.user} est connecté !")
    await setup_roles(bot)
    bot.loop.create_task(start_timers())


async def start_timers():
    timer_A = TimerSession('50-10', 50, 10)
    timer_B = TimerSession('25-5', 25, 5)

    await asyncio.gather(
        timer_A.run(bot, POMODORO_CHANNEL_ID,
                    lambda name: get_participants(name)),
        timer_B.run(bot, POMODORO_CHANNEL_ID,
                    lambda name: get_participants(name)))


def get_participants(name):
    mode = '50-10' if name == '50-10' else '25-5'
    return sessions[mode]


def is_admin():

    async def predicate(ctx):
        return any(role.id == ADMIN_ROLE_ID for role in ctx.author.roles)

    return commands.check(predicate)


async def maintenance_check(ctx):
    if maintenance_mode and not await is_admin().predicate(ctx):
        await ctx.send(
            "\u274C Le bot est actuellement en maintenance. Merci de patienter."
        )
        return True
    return False


# ----------------- Commandes Utilisateurs -----------------


@bot.command(name='join',
             help='Rejoindre une session Pomodoro (A: 50-10 [ou] B: 25-5)')
async def join(ctx, mode: str):
    if await maintenance_check(ctx):
        return
    if mode.upper() == 'A':
        mode = '50-10'
    elif mode.upper() == 'B':
        mode = '25-5'
    await join_session(bot, ctx, mode)


@bot.command(name='leave', help='Quitter une session Pomodoro')
async def leave(ctx):
    if await maintenance_check(ctx):
        return
    await leave_session(bot, ctx)


@bot.command(name='time',
             help='Afficher le temps restant dans le cycle actuel')
async def time(ctx):
    if await maintenance_check(ctx):
        return
    embed = discord.Embed(
        title="Temps restant",
        description=f"Temps restant A: (simulé)\nTemps restant B: (simulé)",
        color=MsgColors.AQUA.value)
    await ctx.send(embed=embed)


@bot.command(name='status', help='Voir l\'état actuel des cycles')
async def status(ctx):
    if await maintenance_check(ctx):
        return
    embed = discord.Embed(
        title="Statut des cycles",
        description=
        f"Status A: Travail\nStatus B: Pause\nStatus actuel: en d\u00e9veloppement (sera li\u00e9 aux cycles de travail/pause)",
        color=MsgColors.AQUA.value)
    await ctx.send(embed=embed)


@bot.command(name='leaderboard', help='Voir les classements')
async def leaderboard(ctx):
    if await maintenance_check(ctx):
        return
    top_global = get_global_leaderboard()
    top_A = get_leaderboard('50-10')
    top_B = get_leaderboard('25-5')
    user_times = get_user_times(ctx.author.id)

    desc = "**\ud83c\udfc6 Classement G\u00e9n\u00e9ral**\n"
    for i, (uid, minutes) in enumerate(top_global, start=1):
        user = await bot.fetch_user(uid)
        desc += f"**#{i}** {user.name} : {minutes} min\n"

    desc += "\n**\ud83d\udcda Mode A (50-10)**\n"
    for i, (uid, minutes) in enumerate(top_A, start=1):
        user = await bot.fetch_user(uid)
        desc += f"**#{i}** {user.name} : {minutes} min\n"

    desc += "\n**\ud83d\udcd6 Mode B (25-5)**\n"
    for i, (uid, minutes) in enumerate(top_B, start=1):
        user = await bot.fetch_user(uid)
        desc += f"**#{i}** {user.name} : {minutes} min\n"

    desc += f"\n**Ton Temps Perso :**\n50-10 \u2794 {user_times.get('50-10',0)} min\n25-5 \u2794 {user_times.get('25-5',0)} min"

    embed = discord.Embed(title="Classements Pomodoro \ud83d\udcda",
                          description=desc,
                          color=MsgColors.PURPLE.value)
    await ctx.send(embed=embed)


@bot.command(name='help', help='Affiche les commandes disponibles')
async def help_command(ctx):
    if await maintenance_check(ctx):
        return
    desc = f"Pr\u00e9fixe : `{COMMAND_PREFIX}`\n\n"
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


@bot.command(name='helpadmin', help='Affiche les commandes admin')
@is_admin()
async def helpadmin(ctx):
    desc = "**Commandes Admin :**\n"
    desc += "`maintenance` : Activer/d\u00e9sactiver le mode maintenance.\n"
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
    if maintenance_mode:
        msg = "\u2692\ufe0f Maintenance activ\u00e9e"
    else:
        msg = "\u2705 Maintenance d\u00e9sactiv\u00e9e"
    embed = discord.Embed(
        title=msg,
        description="Mode maintenance activ\u00e9."
        if maintenance_mode else "Mode maintenance d\u00e9sactiv\u00e9.",
        color=MsgColors.RED.value)
    await ctx.send(embed=embed)


@bot.command(name='reloadtimers', help='Recharger les timers')
@is_admin()
async def reloadtimers(ctx):
    await ctx.send("Timers recharg\u00e9s !")


@bot.command(name='adminping', help='Tester un ping admin')
@is_admin()
async def adminping(ctx):
    await ctx.send("\ud83d\udd8d\ufe0f Pong Admin !\nAdmin ping r\u00e9ussi !")


if __name__ == '__main__':
    bot.run(TOKEN)
