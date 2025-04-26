import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from role_manager import assign_role, remove_role, setup_roles, send_to_pomodoro_channel
from session_manager import SessionManager
from database import Database
from timer import TimerSession
from flask import Flask

# Chargement du fichier .env
load_dotenv()

# Récupération du token Discord
TOKEN = os.getenv('DISCORD_TOKEN')

# Sécurité pour le token Discord
if TOKEN is None or TOKEN == "":
    raise ValueError(
        "❌ Le token Discord n'est pas défini. Vérifiez votre fichier .env ou vos variables d'environnement."
    )

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix='*', intents=intents)

# Initialisation des composants
role_manager = RoleManager()
session_manager = SessionManager()
db = Database()
timer_session = TimerSession(db)

# Flask pour Render
app = Flask(__name__)


@app.route('/')
def home():
    return "Bot is running."


# Fonctions utiles
async def send_embed(ctx, title, description, color=discord.Color.blue()):
    embed = discord.Embed(title=title, description=description, color=color)
    await ctx.send(embed=embed)


# Events
@bot.event
async def on_ready():
    print(f'{bot.user} est connecté.')


# Commandes pour tous
@bot.command()
async def help(ctx):
    if db.is_maintenance():
        await ctx.send(
            "\u274c Le bot est actuellement en maintenance. Merci de patienter."
        )
        return
    embed = discord.Embed(title="Commandes disponibles",
                          color=discord.Color.green())
    embed.add_field(name="*join (A: 50-10 ou B: 25-5)",
                    value="Rejoindre une session.",
                    inline=False)
    embed.add_field(name="*leave", value="Quitter une session.", inline=False)
    embed.add_field(name="*time", value="Voir le temps restant.", inline=False)
    embed.add_field(name="*status",
                    value="Voir le statut actuel.",
                    inline=False)
    embed.add_field(name="*leaderboard",
                    value="Voir le classement.",
                    inline=False)
    embed.add_field(name="*helpadmin", value="Commandes admin.", inline=False)
    await ctx.send(embed=embed)


@bot.command()
async def helpadmin(ctx):
    embed = discord.Embed(title="Commandes Admin", color=discord.Color.red())
    embed.add_field(name="*maintenance",
                    value="Activer/désactiver la maintenance.",
                    inline=False)
    embed.add_field(name="*adminping",
                    value="Tester la latence du bot (admin).",
                    inline=False)
    embed.add_field(name="*pingtest",
                    value="Tester la latence du bot (admin caché).",
                    inline=False)
    await ctx.send(embed=embed)


@bot.command()
async def join(ctx, mode: str = None):
    if db.is_maintenance():
        await ctx.send(
            "\u274c Le bot est actuellement en maintenance. Merci de patienter."
        )
        return

    if mode is None:
        await send_embed(ctx, "Erreur",
                         "Veuillez spécifier un mode: A (50-10) ou B (25-5)",
                         discord.Color.red())
        return

    mode = mode.lower()
    if mode in ["50-10", "a"]:
        await role_manager.add_role(ctx.author, "50-10")
        await send_embed(ctx, "Succès", "Vous avez rejoint la session 50-10.")
    elif mode in ["25-5", "b"]:
        await role_manager.add_role(ctx.author, "25-5")
        await send_embed(ctx, "Succès", "Vous avez rejoint la session 25-5.")
    else:
        await send_embed(ctx, "Erreur",
                         "Mode invalide. Choisissez A (50-10) ou B (25-5).",
                         discord.Color.red())


@bot.command()
async def leave(ctx):
    if db.is_maintenance():
        await ctx.send(
            "\u274c Le bot est actuellement en maintenance. Merci de patienter."
        )
        return

    await role_manager.remove_roles(ctx.author)
    await send_embed(ctx, "Succès", "Vous avez quitté votre session.")


@bot.command()
async def time(ctx):
    if db.is_maintenance():
        await ctx.send(
            "\u274c Le bot est actuellement en maintenance. Merci de patienter."
        )
        return

    times = timer_session.get_times()
    embed = discord.Embed(title="Temps Restant", color=discord.Color.blue())
    embed.add_field(name="50-10",
                    value=f"{times['50-10']} minutes",
                    inline=True)
    embed.add_field(name="25-5", value=f"{times['25-5']} minutes", inline=True)
    await ctx.send(embed=embed)


@bot.command()
async def status(ctx):
    if db.is_maintenance():
        await ctx.send(
            "\u274c Le bot est actuellement en maintenance. Merci de patienter."
        )
        return

    status = timer_session.get_status()
    embed = discord.Embed(title="Statut Actuel",
                          description=f"{status}",
                          color=discord.Color.blue())
    await ctx.send(embed=embed)


@bot.command()
async def leaderboard(ctx):
    if db.is_maintenance():
        await ctx.send(
            "\u274c Le bot est actuellement en maintenance. Merci de patienter."
        )
        return

    leaderboard = db.get_leaderboard()
    embed = discord.Embed(title="Leaderboard", color=discord.Color.gold())
    for name, score in leaderboard:
        embed.add_field(name=name, value=f"{score} points", inline=False)
    await ctx.send(embed=embed)


# Commandes admin
@bot.command()
async def maintenance(ctx):
    if db.toggle_maintenance():
        await send_embed(ctx, "Maintenance",
                         "Maintenance activée \U0001F6E0\uFE0F",
                         discord.Color.red())
    else:
        await send_embed(ctx, "Maintenance", "Maintenance désactivée \u2705",
                         discord.Color.green())


@bot.command()
async def adminping(ctx):
    latency = round(bot.latency * 1000)
    await send_embed(ctx, "Admin Ping", f"Latence: {latency}ms")


@bot.command()
async def pingtest(ctx):
    latency = round(bot.latency * 1000)
    await send_embed(ctx, "Ping Test", f"Latence: {latency}ms")


# Lancement
async def main():
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))))
    loop.run_until_complete(main())
