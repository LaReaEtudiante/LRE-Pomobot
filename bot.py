import os
import discord
from dotenv import load_dotenv
from discord.ext import commands, tasks
import configparser
import asyncio
from enum import Enum
from database import ajouter_temps, recuperer_temps, classement_top10
#from timer import Timer, TimerStatus # Plus besoin de Timer ou TimerStatus
from keep_alive import keep_alive
import logging  # Import du module logging

DEBUG = True
MAINTENANCE_MODE = False  # Variable pour le mode maintenance
POMODORO_ROLE_NAME = "50-10"
PARTICIPANTS = []  # Liste des IDs des participants au Pomodoro

load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
TOKEN = os.getenv('DISCORD_TOKEN')
bot = commands.Bot(command_prefix="*",
                   help_command=None,
                   intents=intents)

# Configuration du logging
logger = logging.getLogger('pomodoro_bot')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('pomodoro_bot.log', encoding='utf-8')
fh_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
fh.setFormatter(fh_formatter)
logger.addHandler(fh)


class MsgColors(Enum):
    AQUA = 0x33c6bb
    YELLOW = 0xFFD966
    RED = 0xEA3546
    PURPLE = 0x6040b1


def is_admin():
    async def predicate(ctx):
        return ctx.message.author.guild_permissions.administrator
    return commands.check(predicate)


def check_maintenance_mode():  # Décorateur pour le mode maintenance
    async def predicate(ctx):
        if MAINTENANCE_MODE and ctx.command.name != 'maintenance':
            raise commands.CommandError("Bot en mode maintenance.")
        return True
    return commands.check(predicate)


@bot.event
async def on_ready():
    print(f'{bot.user} est connecté à Discord.')
    logger.info(f'{bot.user} est connecté à Discord.')  # Log au démarrage
    pomodoro_loop.start()  # Démarrer la boucle Pomodoro


@bot.event
async def on_message(message):
    await bot.process_commands(message)


@bot.command(name='maintenance', help='Active/désactive le mode maintenance (admin only)')
@is_admin()
async def maintenance(ctx):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    if MAINTENANCE_MODE:
        await ctx.send("Bot en mode maintenance. Les commandes sont désactivées.")
        logger.warning("Bot mis en mode maintenance.")
    else:
        await ctx.send("Bot en mode normal. Les commandes sont activées.")
        logger.info("Bot sorti du mode maintenance.")


@bot.command(name='join', help='Rejoindre le Pomodoro')
@check_maintenance_mode()
async def join_pomodoro(ctx):
    global PARTICIPANTS
    user = ctx.author
    if user.id not in PARTICIPANTS:
        PARTICIPANTS.append(user.id)
        # Gestion du rôle "50-10"
        role = discord.utils.get(ctx.guild.roles, name=POMODORO_ROLE_NAME)
        if role is None:
            role = await ctx.guild.create_role(name=POMODORO_ROLE_NAME)
            await ctx.send(f"Rôle '{POMODORO_ROLE_NAME}' créé.")
            logger.info(f"Rôle '{POMODORO_ROLE_NAME}' créé.")
        await user.add_role(role)
        await ctx.send(f"{user.mention} a rejoint le Pomodoro.")
        logger.info(f"{user.name} a rejoint le Pomodoro.")
    else:
        await ctx.send(f"{user.mention} est déjà dans le Pomodoro.")


@bot.command(name='leave', help='Quitter le Pomodoro')
@check_maintenance_mode()
async def leave_pomodoro(ctx):
    global PARTICIPANTS
    user = ctx.author
    if user.id in PARTICIPANTS:
        PARTICIPANTS.remove(user.id)
        # Retirer le rôle "50-10"
        role = discord.utils.get(ctx.guild.roles, name=POMODORO_ROLE_NAME)
        if role is not None:
            await user.remove_role(role)
        await ctx.send(f"{user.mention} a quitté le Pomodoro.")
        logger.info(f"{user.name} a quitté le Pomodoro.")
    else:
        await ctx.send(f"{user.mention} n'est pas dans le Pomodoro.")


@bot.command(name='leaderboard', help='Affiche le classement du serveur')
@check_maintenance_mode()
async def leaderboard(ctx):
    top10 = classement_top10(ctx.guild.id)
    user_time = recuperer_temps(ctx.author.id, ctx.guild.id)
    description = ''
    for index, (user_id, total_minutes) in enumerate(top10, start=1):
        user = await bot.fetch_user(user_id)
        description += f'**#{index}** {user.name} : {total_minutes} minutes\n'
    if ctx.author.id not in [u[0] for u in top10]:
        description += f'\n**Ton temps personnel** : {user_time} minutes'
    embed = discord.Embed(title="🏆 Leaderboard Pomodoro",
                          description=description,
                          color=MsgColors.PURPLE.value)
    await ctx.send(embed=embed)


@bot.command(name='help', help='Décrit toutes les commandes du bot.')
@check_maintenance_mode()
async def help(ctx):
    help_commands = dict()
    for command in bot.commands:
        help_commands[command.name] = command.help

    desc = 'Le préfixe pour ce bot est `' + COMMAND_PREFIX + '`\n'
    desc += '\n**Commandes Pomodoro**\n'
    desc += '`{:12s}` {}\n'.format('join', help_commands.get('join', ''))
    desc += '`{:12s}` {}\n'.format('leave', help_commands.get('leave', ''))

    desc += '\n**Commandes générales**\n'
    desc += '`{:12s}` {}\n'.format('help', help_commands.get('help', ''))
    desc += '`{:12s}` {}\n'.format('leaderboard', help_commands.get('leaderboard', ''))
    desc += '`{:12s}` {}\n'.format('maintenance', help_commands.get('maintenance', ''))

    embed = discord.Embed(title='Commandes du Bot',
                       description=desc,
                       color=MsgColors.PURPLE.value)
    await ctx.send(embed=embed)


@bot.command(name='set_pomodoro', help='Définit les temps du Pomodoro (admin only)')
@is_admin()
@check_maintenance_mode()
async def set_pomodoro(ctx, work_time: int, break_time: int):
    config.set('CURRENT_SETTINGS', 'work_time', str(work_time))
    config.set('CURRENT_SETTINGS', 'break_time', str(break_time))
    with open('settings.ini', 'w') as configFile:
        config.write(configFile)
    await ctx.send(f"Pomodoro réglé sur {work_time} minutes de travail et {break_time} minutes de pause.")
    logger.info(f"Pomodoro réglé sur {work_time} minutes de travail et {break_time} minutes de pause.")


@tasks.loop(minutes=1)  # La boucle tourne toutes les minutes
async def pomodoro_loop():
    work_time = int(config['CURRENT_SETTINGS']['work_time'])
    break_time = int(config['CURRENT_SETTINGS']['break_time'])
    channel = bot.get_channel(1199346210421295177)  # ID du canal où envoyer les messages
    if channel is not None:
        await channel.send(f"Début de la session de travail ({work_time} minutes) ! {get_role_mention(channel.guild)}")
        logger.info(f"Début de la session de travail ({work_time} minutes).")
        for minute in range(work_time):
            await asyncio.sleep(60)  # Attendre une minute
            if minute % 5 == 0:
                remaining = work_time - minute - 1
                await channel.send(f"{remaining} minutes restantes.")
        await channel.send(f"Début de la pause ({break_time} minutes) ! {get_role_mention(channel.guild)}")
        logger.info(f"Début de la pause ({break_time} minutes).")
        for _ in range(break_time):
            await asyncio.sleep(60)  # Attendre une minute
        if PARTICIPANTS:  # Ajouter le temps de travail à chaque participant
            for user_id in PARTICIPANTS:
                ajouter_temps(user_id, channel.guild.id, work_time)
            logger.info(f"Temps de travail ajouté aux participants : {PARTICIPANTS}")
        else:
            await channel.send("Aucun participant à cette session.")
            logger.info("Aucun participant à cette session.")


def get_role_mention(guild: discord.Guild):
    role = discord.utils.get(guild.roles, name=POMODORO_ROLE_NAME)
    if role:
        return role.mention
    return "@everyone"  # Retourner @everyone si le rôle n'existe pas (au cas où)


# ----------------------- ERROR HANDLING -----------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandError) and str(error) == "Bot en mode maintenance.":
        await ctx.send("Le bot est actuellement en mode maintenance. Veuillez réessayer plus tard.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Argument manquant. Veuillez vérifier la commande.")
    elif isinstance(error, commands.errors.CheckFailure):
        await ctx.send("Vous n'avez pas la permission d'utiliser cette commande.")
    else:
        await ctx.send(f"Une erreur est survenue : {error}")
        logger.error(f"Erreur lors de l'exécution de la commande : {error}")


if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('settings.ini')
    keep_alive()
    bot.run(TOKEN)