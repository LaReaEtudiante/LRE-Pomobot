import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from role_manager import RoleManager
from session_manager import SessionManager
from database import Database
from timer import TimerSession
from keep_alive import keep_alive

# Load .env
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    raise RuntimeError("Le token Discord n'est pas défini.")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix='*', intents=intents)

# Instances
db = Database()
role_manager = RoleManager()
session_manager = SessionManager()

# Durées par défaut
MODES = {'50-10': (50, 10), '25-5': (25, 5)}

# Keep alive
keep_alive()

@bot.event
async def on_ready():
    print(f"{bot.user} connecté.")
    # Créer les rôles si nécessaire
    await role_manager.setup_roles(bot)
    # Démarrer un TimerSession pour chaque mode
    for mode, (w, b) in MODES.items():
        timer = TimerSession(mode, w, b)
        # callback qui récupère les participants dans le premier guild
        def get_parts(name, _mode=mode):
            guild = bot.guilds[0]
            return session_manager.get_participants(_mode, guild)
        asyncio.create_task(timer.run(bot, role_manager.POMODORO_CHANNEL_ID, get_parts))

# Helper embed
async def send_embed(ctx, title, desc, color=discord.Color.blue()):
    embed = discord.Embed(title=title, description=desc, color=color)
    await ctx.send(embed=embed)

# Vérification maintenance
def check_maintenance(ctx):
    if db.is_maintenance():
        raise commands.CheckFailure("Maintenance active")

# Commands
@bot.command()
@commands.check(check_maintenance)
async def join(ctx, mode: str = None):
    if mode is None:
        return await send_embed(ctx, "Erreur", "Spécifier A(50-10) ou B(25-5).", discord.Color.red())
    m = '50-10' if mode.lower() in ['50-10','a'] else '25-5'
    ok, msg = await session_manager.join(ctx.author, m)
    if not ok:
        return await send_embed(ctx, "⚠️", msg, discord.Color.orange())
    await role_manager.add_role(ctx.author, m)
    await send_embed(ctx, "Succès", f"Session {m} rejointe !", discord.Color.green())

@bot.command()
@commands.check(check_maintenance)
async def leave(ctx):
    ok, mode = await session_manager.leave(ctx.author)
    if not ok:
        return await send_embed(ctx, "⚠️", "Tu n'es dans aucune session.", discord.Color.orange())
    await role_manager.remove_roles(ctx.author)
    await send_embed(ctx, "Succès", f"Session {mode} quittée.", discord.Color.green())

@bot.command()
@commands.check(check_maintenance)
async def time(ctx):
    times = {m: ts.time_left for m,(w,b) in MODES.items() for ts in []}  # exemple simple
    # Si besoin, on peut stocker état dans session_manager
    await send_embed(ctx, "Temps Restant", str(times))

@bot.command()
@commands.check(check_maintenance)
async def leaderboard(ctx, mode: str = None):
    lb = db.get_leaderboard(mode)  # mode None = global
    desc = "\n".join(f"<@{uid}>: {pts} min" for uid,pts in lb)
    await send_embed(ctx, "Leaderboard", desc, discord.Color.gold())

@bot.command()
@commands.is_owner()
async def maintenance(ctx):
    new = db.toggle_maintenance()
    color = discord.Color.red() if new else discord.Color.green()
    msg = "Maintenance activée." if new else "Maintenance désactivée."
    await send_embed(ctx, "Maintenance", msg, color)

# Run
bot.run(TOKEN)