import os
import asyncio
import datetime
import pytz
from threading import Thread

import discord
from discord.ext import commands
from tinydb import TinyDB, Query
from flask import Flask
from dotenv import load_dotenv

# ----------------------------
# Keep-alive (Flask)
# ----------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# ----------------------------
# Base de données (TinyDB)
# ----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'sessions.json')

class Database:
    def __init__(self):
        self.db = TinyDB(DB_PATH)
        self.User = Query()

    def save_time(self, user_id: int, mode: str, minutes: int):
        user = self.db.get(self.User.user_id == user_id)
        if user:
            new_total = user.get(mode, 0) + minutes
            self.db.update({mode: new_total}, self.User.user_id == user_id)
        else:
            self.db.insert({
                'user_id': user_id,
                '50-10': minutes if mode == '50-10' else 0,
                '25-5': minutes if mode == '25-5' else 0,
                'maintenance': False
            })

    def get_user_times(self, user_id: int):
        user = self.db.get(self.User.user_id == user_id)
        if user:
            return {k: user.get(k, 0) for k in ['50-10', '25-5']}
        return {'50-10': 0, '25-5': 0}

    def get_leaderboard(self, mode: str = None):
        users = self.db.all()
        if mode:
            key = lambda x: x.get(mode, 0)
        else:
            key = lambda x: x.get('50-10', 0) + x.get('25-5', 0)
        sorted_users = sorted(users, key=key, reverse=True)[:10]
        return [(u['user_id'], key(u)) for u in sorted_users]

    def is_maintenance(self):
        record = self.db.get(self.User.user_id == 0)
        return bool(record and record.get('maintenance', False))

    def toggle_maintenance(self):
        record = self.db.get(self.User.user_id == 0)
        if record:
            new = not record.get('maintenance', False)
            self.db.update({'maintenance': new}, self.User.user_id == 0)
            return new
        else:
            self.db.insert({'user_id': 0, 'maintenance': True})
            return True

# ----------------------------
# Gestion des rôles
# ----------------------------
class RoleManager:
    ROLE_50_10 = '50-10'
    ROLE_25_5 = '25-5'
    POMODORO_CHANNEL_ID = 1365678171671892018  # Modifier selon serveur

    async def setup_roles(self, bot):
        for guild in bot.guilds:
            existing = {r.name for r in guild.roles}
            if self.ROLE_50_10 not in existing:
                await guild.create_role(name=self.ROLE_50_10,
                                        color=discord.Color.blue())
            if self.ROLE_25_5 not in existing:
                await guild.create_role(name=self.ROLE_25_5,
                                        color=discord.Color.green())

    async def add_role(self, member: discord.Member, mode: str):
        role_name = self.ROLE_50_10 if mode == self.ROLE_50_10 else self.ROLE_25_5
        role = discord.utils.get(member.guild.roles, name=role_name)
        if role:
            await member.add_roles(role)

    async def remove_roles(self, member: discord.Member):
        for rn in (self.ROLE_50_10, self.ROLE_25_5):
            role = discord.utils.get(member.guild.roles, name=rn)
            if role and role in member.roles:
                await member.remove_roles(role)

    async def send_to_pomodoro(self, bot, embed: discord.Embed):
        for guild in bot.guilds:
            channel = discord.utils.get(
                guild.text_channels,
                id=self.POMODORO_CHANNEL_ID
            )
            if channel:
                await channel.send(embed=embed)

# ----------------------------
# Gestion des sessions
# ----------------------------
class SessionManager:
    def __init__(self):
        self.sessions = {'50-10': set(), '25-5': set()}

    async def join(self, member: discord.Member, mode: str):
        other = '25-5' if mode == '50-10' else '50-10'
        if member.id in self.sessions[other]:
            return False, f"Tu es déjà dans la session {other}."
        if member.id in self.sessions[mode]:
            return False, f"Tu es déjà dans la session {mode}."
        self.sessions[mode].add(member.id)
        return True, None

    async def leave(self, member: discord.Member):
        for mode, users in self.sessions.items():
            if member.id in users:
                users.remove(member.id)
                return True, mode
        return False, None

    def get_participants(self, mode: str, guild: discord.Guild):
        return [guild.get_member(uid) for uid in self.sessions[mode]
                if guild.get_member(uid) is not None]

# ----------------------------
# Timer Pomodoro
# ----------------------------
class TimerSession:
    def __init__(self, name: str, work: int, pause: int):
        self.name = name
        self.work_duration = work
        self.break_duration = pause
        self.is_working = True
        self.time_left = work

    async def run(self, bot, guild_id: int, get_parts):
        tz = pytz.timezone('Europe/Paris')
        await bot.wait_until_ready()
        channel = bot.get_channel(RoleManager.POMODORO_CHANNEL_ID)
        while True:
            now = datetime.datetime.now(tz)
            await asyncio.sleep(60 - now.second)
            guild = discord.utils.get(bot.guilds, id=guild_id)
            if not guild:
                continue
            participants = get_parts(self.name)
            if not participants:
                continue
            self.time_left -= 1
            if self.is_working:
                db = Database()
                for m in participants:
                    db.save_time(m.id, self.name, 1)
            if self.time_left <= 0:
                self.is_working = not self.is_working
                self.time_left = (self.work_duration if self.is_working else
                                  self.break_duration)
                state = "Session de travail" if self.is_working else "Pause"
                mentions = ' '.join(m.mention for m in participants)
                embed = discord.Embed(
                    title=f"⏰ {state} {self.name}",
                    description=f"{mentions}\nParticipants : {len(participants)}",
                    color=discord.Color.purple()
                )
                await channel.send(embed=embed)

# ----------------------------
# Bot principal
# ----------------------------
def main():
    load_dotenv()
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        raise RuntimeError("Token non défini dans .env")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    bot = commands.Bot(command_prefix='*', intents=intents)

    db = Database()
    rm = RoleManager()
    sm = SessionManager()
    MODES = {'50-10': (50, 10), '25-5': (25, 5)}
    timers = {}

    keep_alive()

    @bot.event
    async def on_ready():
        print(f"{bot.user} connecté.")
        await rm.setup_roles(bot)
        # Créer et stocker les timers par guild & mode
        for guild in bot.guilds:
            for mode, (w, p) in MODES.items():
                key = (guild.id, mode)
                timer = TimerSession(mode, w, p)
                timers[key] = timer
                def get_parts(name, _guild=guild, _mode=mode):
                    return sm.get_participants(_mode, _guild)
                asyncio.create_task(
                    timer.run(bot, guild.id, get_parts)
                )

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("⚠️ Commande indisponible (maintenance ou permissions)")
        else:
            print(f"Erreur commande: {error}")
            await ctx.send("❌ Une erreur est survenue.")

    @bot.command()
    async def join(ctx, mode: str = None):
        if db.is_maintenance():
            return await ctx.send("🚧 Maintenance active.")
        if mode is None:
            return await ctx.send("❌ Spécifiez A (50-10) ou B (25-5).")
        m = '50-10' if mode.lower() in ['50-10', 'a'] else '25-5'
        ok, msg = await sm.join(ctx.author, m)
        if not ok:
            return await ctx.send(f"⚠️ {msg}")
        await rm.add_role(ctx.author, m)
        await ctx.send(f"✅ Session {m} rejointe.")

    @bot.command()
    async def leave(ctx):
        if db.is_maintenance():
            return await ctx.send("🚧 Maintenance active.")
        ok, mode = await sm.leave(ctx.author)
        if not ok:
            return await ctx.send("⚠️ Vous n'êtes dans aucune session.")
        await rm.remove_roles(ctx.author)
        await ctx.send(f"✅ Session {mode} quittée.")

    @bot.command()
    async def time(ctx):
        if db.is_maintenance():
            return await ctx.send("🚧 Maintenance active.")
        lines = []
        for mode in MODES:
            key = (ctx.guild.id, mode)
            timer = timers.get(key)
            if timer:
                status = 'Travail' if timer.is_working else 'Pause'
                lines.append(f"{mode} ({status}) : {timer.time_left} min")
        await ctx.send("\n".join(lines) or "Aucun timer trouvé.")

    @bot.command()
    async def leaderboard(ctx, mode: str = None):
        if db.is_maintenance():
            return await ctx.send("🚧 Maintenance active.")
        lb = db.get_leaderboard(mode)
        text = "\n".join(f"<@{uid}> : {pts} min" for uid, pts in lb)
        await ctx.send(f"🏆 **Leaderboard**\n{text}")

    @bot.command()
    @commands.is_owner()
    async def maintenance(ctx):
        new = db.toggle_maintenance()
        msg = "⚙️ Maintenance activée." if new else "✅ Maintenance désactivée."
        await ctx.send(msg)

    @bot.command()
    async def helpadmin(ctx):
        await ctx.send(
            "`*join [A|B]`, `*leave`, `*time`, `*leaderboard [mode]`, `*maintenance` (owner)`"
        )

    bot.run(TOKEN)

if __name__ == '__main__':
    main()