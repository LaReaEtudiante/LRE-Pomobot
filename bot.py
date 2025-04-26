import os
import discord
from dotenv import load_dotenv
from discord.ext import commands
import configparser
import asyncio
from enum import Enum
from database import ajouter_temps, recuperer_temps, classement_top10
from timer import Timer, TimerStatus
from keep_alive import keep_alive

DEBUG = True  # For debug messages
SETTING_OPTIONS = [
    'work_time', 'short_break_time', 'long_break_time', 'sessions',
    'use_long_breaks'
]
COMMAND_PREFIX = '*'
TIMER_COMMANDS = [
    'start', 'pause', 'stop', 'time', 'notify', 'set', 'setextra',
    'togglebreak'
]
GENERAL_COMMANDS = ['reset', 'help']

load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
TOKEN = os.getenv('DISCORD_TOKEN')  # Grabs Discord bot token from .env file
bot = commands.Bot(command_prefix=COMMAND_PREFIX,
                   help_command=None,
                   intents=intents)
timer = Timer()
pingList = []

# ------------ Overall Work List ---------
# TODO: Complete remaining commands
# TODO: Complete all error handling
# TODO: Store user-set times
# TODO: Add break functionality + settings to adjust long breaks, sessions
# TODO: Add docstrings
# TODO: Create empty .env file before finalizing
# TODO: Remove all DEBUG statements and check imports before finalizing


# TODO: Update Enum with more colors
class MsgColors(Enum):
    AQUA = 0x33c6bb
    YELLOW = 0xFFD966
    RED = 0xEA3546
    PURPLE = 0x6040b1


@bot.event
async def on_ready():
    print(f'{bot.user} est connecté à Discord.')


@bot.event
async def on_message(message):
    print(f"Message reçu : {message.content}")

    await bot.process_commands(
        message)  # TRÈS important pour que les commandes fonctionnent !!


@bot.command(
    name='start',
    help='Démarre un minuteur Pomodoro ou le reprend si il est en pause')
async def start_timer(ctx):
    if timer.get_status() == TimerStatus.STOPPED:
        work_mins = config['CURRENT_SETTINGS'][
            'work_time']  # Grabs work duration from user settings
        work_secs = '00'
        desc = f'Temps restant: `{work_mins}:{work_secs}`'  # Formats message to be sent

        em = discord.Embed(title=':timer: Démarrage du minuteur',
                           description=desc,
                           color=MsgColors.AQUA.value)
        await ctx.send(embed=em)
        if DEBUG:
            print('Commande: *start (depuis arrêté)')

        work_time = int(work_mins) * 60  # Multiplied by 60 to get seconds
        timer.start(work_time)
        while timer.get_status() == TimerStatus.RUNNING:
            await asyncio.sleep(1)  # Sleep for 1 sec before timer counts down
            timer.tick()
        if timer.get_status(
        ) == TimerStatus.STOPPED:  # Ping users when timer stops
            ajouter_temps(ctx.author.id, ctx.guild.id,
                          int(config['CURRENT_SETTINGS']['work_time']))
            for user in pingList:
                await ctx.send(f'Pinging {user}')
            pingList.clear()

    elif timer.get_status(
    ) == TimerStatus.PAUSED:  # Resuming timer from paused state
        em = discord.Embed(title=':timer: Reprise du minuteur',
                           description=getFrmtTime(timer),
                           color=MsgColors.AQUA.value)
        await ctx.send(embed=em)
        if DEBUG:
            print('Commande: *start (depuis pause)')

        timer.resume()
        while timer.get_status() == TimerStatus.RUNNING:
            await asyncio.sleep(1)
            timer.tick()
        if timer.get_status(
        ) == TimerStatus.STOPPED:  # Ping users when timer stops
            ajouter_temps(ctx.author.id, ctx.guild.id,
                          int(config['CURRENT_SETTINGS']['work_time']))
            for user in pingList:
                await ctx.send(f'Pinging {user}')
            pingList.clear()
    else:
        em = discord.Embed(title=':warning: Attention',
                           description='Le minuteur est déjà en cours.',
                           color=MsgColors.YELLOW.value)
        await ctx.send(embed=em)


@bot.command(name='pause', help='Met en pause le minuteur')
async def pause_timer(ctx):
    if not timer.pause():
        em = discord.Embed(
            title=':warning: Attention',
            description='Le minuteur est déjà en pause ou arrêté.',
            color=MsgColors.YELLOW.value)
    else:
        em = discord.Embed(title=':pause_button: Minuteur en pause',
                           description='Le minuteur est en pause.\n' +
                           getFrmtTime(timer),
                           color=MsgColors.AQUA.value)
    await ctx.send(embed=em)


@bot.command(name='stop', help='Arrête le minuteur')
async def stop_timer(ctx):
    if not timer.stop():
        em = discord.Embed(
            title=':warning: Attention',
            description='Le minuteur est déjà arrêté ou en pause.',
            color=MsgColors.YELLOW.value)
    else:
        em = discord.Embed(title=':stop_button: Minuteur arrêté',
                           description='Le minuteur a été arrêté.',
                           color=MsgColors.RED.value)
        pingList.clear()  # Clear ping list when timer stops
    await ctx.send(embed=em)


@bot.command(name='time',
             help='Affiche l\'état actuel du minuteur',
             aliases=['timer', 'status'])
async def current_time(ctx):
    status = timer.get_status()
    if status == TimerStatus.STOPPED:
        em = discord.Embed(title=':stop_button: Minuteur arrêté',
                           description='Temps restant : 0:00',
                           color=MsgColors.RED.value)
    elif status == TimerStatus.RUNNING:
        em = discord.Embed(title=':timer: Minuteur en cours',
                           description=getFrmtTime(timer),
                           color=MsgColors.AQUA.value)
    else:
        em = discord.Embed(title=':pause_button: Minuteur en pause',
                           description=getFrmtTime(timer),
                           color=MsgColors.YELLOW.value)
    await ctx.send(embed=em)


@bot.command(name='notify', help='Te prévient à la fin du minuteur')
async def notify_user(ctx):
    em = discord.Embed(title=':ballot_box_with_check: Notification activée',
                       description='Le minuteur mentionnera ' +
                       ctx.message.author.name + ' à la fin du décompte.',
                       color=MsgColors.AQUA.value)
    pingList.append(ctx.message.author.mention)
    await ctx.send(embed=em)


@bot.command(name='set', help='Définit la durée de travail et de pause courte')
async def set_options_simple(ctx, work_time: int, short_break_time: int):
    config.set('CURRENT_SETTINGS', 'work_time', str(work_time))
    config.set('CURRENT_SETTINGS', 'short_break_time', str(short_break_time))
    with open('settings.ini', 'w') as configFile:
        config.write(configFile)

    em = discord.Embed(
        title=':gear: Réglage du minuteur',
        description=
        f'Temps de travail défini à {work_time} min et pause courte à {short_break_time} min',
        color=MsgColors.AQUA.value)
    await ctx.send(embed=em)

    if DEBUG:
        print(
            f'Command: *set: Work Time: {work_time} Break Time: {short_break_time}'
        )


@bot.command(name='setextra',
             help='Définit la durée de travail et de longue pause')
async def set_options_extra(ctx, long_break_time: int, sessions: int):
    config.set('CURRENT_SETTINGS', 'long_break_time', str(long_break_time))
    config.set('CURRENT_SETTINGS', 'sessions', str(sessions))
    with open('settings.ini', 'w') as configFile:
        config.write(configFile)

    em = discord.Embed(
        title=':gear: Réglage du minuteur',
        description=
        f'Longue pause réglée à {long_break_time} minutes et nombre de sessions de travail à {sessions}.',
        color=MsgColors.AQUA.value)
    await ctx.send(embed=em)


@bot.command(name='togglebreak',
             help='Activer ou désactiver les longues pauses')
async def toggle_long_break(ctx):
    break_option = config['CURRENT_SETTINGS']['use_long_breaks'] == 'True'
    config.set('CURRENT_SETTINGS', 'use_long_breaks', str(not break_option))
    with open('settings.ini', 'w') as configFile:
        config.write(configFile)

    if break_option:
        desc = 'Les longues pauses ont été désactivées.'
    else:
        desc = 'Les longues pauses ont été activées.'
    em = discord.Embed(title=':gear: Réglage du minuteur',
                       description=desc,
                       color=MsgColors.AQUA.value)
    await ctx.send(embed=em)


@bot.command(name='leaderboard', help='Affiche le classement du serveur')
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


@bot.command(name='reset', help='Réinitialiser les paramètres du minuteur')
async def reset_settings(ctx):
    for option in SETTING_OPTIONS:
        config.set('CURRENT_SETTINGS', option, config['DEFAULT'][option])
    with open('settings.ini', 'w') as configFile:
        config.write(configFile)
    em = discord.Embed(
        title=':leftwards_arrow_with_hook: Reset Timer Settings',
        description=
        'Les paramètres du minuteur ont été réinitialisés aux valeurs par défaut.',
        color=MsgColors.AQUA.value)
    await ctx.send(embed=em)


@bot.command(name='help', help='Décrit toutes les commandes du bot.')
async def help(ctx):
    # TODO: Fill in help command
    help_commands = dict()  # Dict of help commands + their description
    for command in bot.commands:
        help_commands[command.name] = command.help

    desc = 'Le préfixe pour ce bot est `' + COMMAND_PREFIX + '`\n'  # Prints ordered list of timer commands
    desc += f'\n**Commandes du minuteur | {len(TIMER_COMMANDS)}**\n'
    for command in TIMER_COMMANDS:
        desc += '`{:12s}` {}\n'.format(command, help_commands[command])

    desc += f'\n**Commandes générales | {len(GENERAL_COMMANDS)}**\n'  # Prints ordered list of general commands
    for command in GENERAL_COMMANDS:
        desc += '`{:12s}` {}\n'.format(command, help_commands[command])

    em = discord.Embed(title='Commandes du Bot',
                       description=desc,
                       color=MsgColors.PURPLE.value)
    await ctx.send(embed=em)


# TODO: Remove command later
@bot.command(name='t', help='Temporary for testing commands')
async def t(ctx):
    await ctx.send(config['CURRENT_SETTINGS']['use_long_breaks'])


# ----------------------- ERROR HANDLING -----------------------------
# TODO: Fill in remaining method errors
@set_options_simple.error
async def set_options_simple_error(ctx, error):
    if DEBUG:
        print(f'*set error: {ctx.message.content} \n{ctx.message}\n')
    if isinstance(error, commands.errors.MissingRequiredArgument):
        em = discord.Embed(
            title=':warning: Utilisation invalide de la commande *set',
            description=
            'Spécifiez une durée de travail et de pause valide.\nFormat : `*set # #`',
            color=MsgColors.YELLOW.value)
    elif isinstance(error, commands.errors.BadArgument):
        em = discord.Embed(
            title=':warning: Utilisation invalide de la commande *set',
            description=
            'Spécifiez des nombres entiers pour les temps de travail et de pause.\nFormat : `*set # #`',
            color=MsgColors.YELLOW.value)
    else:
        em = discord.Embed(
            title=':x: Erreur inconnue lors de l\'utilisation de *set',
            description=f'Une erreur inconnue a été enregistrée.',
            color=MsgColors.RED.value)
        with open('error.log', 'a') as errorLog:
            errorLog.write(
                f'Unhandled *set message: {ctx.message.content} \n{ctx.message}\n'
            )
    await ctx.send(embed=em)


# ----------------------- UTILITY FUNCTIONS -----------------------------
def getFrmtTime(clock: Timer):
    work_secs = clock.get_time() % 60
    work_mins = int((clock.get_time() - work_secs) / 60)
    if work_secs < 10:  # Formats seconds if <10 seconds left
        work_secs = '0' + str(work_secs)

    return f'Temps restant: `{work_mins}:{work_secs}`'


if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('settings.ini')  # Read in settings from settings.ini
    keep_alive()
    bot.run(TOKEN)
