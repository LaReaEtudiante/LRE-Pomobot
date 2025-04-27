    import os
    import discord
    from discord.ext import commands
    from dotenv import load_dotenv
    import asyncio
    from pytz import timezone
    from datetime import datetime
    from tinydb import TinyDB, Query
    from flask import Flask
    from threading import Thread

    # --- Chargement des variables d'environnement ---
    load_dotenv()
    TOKEN = os.getenv('DISCORD_TOKEN')
    POMODORO_CHANNEL_ID = int(os.getenv('POMODORO_CHANNEL_ID', 0))  # Assurez-vous que la variable est définie dans .env

    # --- Configuration des intents Discord ---
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True  # Nécessaire pour lire le contenu des messages

    bot = commands.Bot(command_prefix='*', intents=intents)

    # --- Configuration de la base de données TinyDB ---
    db = TinyDB('sessions.json')
    User = Query()

    # --- Variables globales ---
    maintenance_mode = False

    # --- Classe RoleManager ---
    class RoleManager:
        ROLE_50_10 = 'Pomodoro 50-10'
        ROLE_25_5 = 'Pomodoro 25-5'
        POMODORO_CHANNEL_ID = POMODORO_CHANNEL_ID

        async def setup_roles(self, guild):
            role_50 = discord.utils.get(guild.roles, name=self.ROLE_50_10)
            if role_50 is None:
                await guild.create_role(name=self.ROLE_50_10)

            role_25 = discord.utils.get(guild.roles, name=self.ROLE_25_5)
            if role_25 is None:
                await guild.create_role(name=self.ROLE_25_5)

        async def add_role(self, member, mode):
            role_name = self.ROLE_50_10 if mode == '50-10' else self.ROLE_25_5
            role = discord.utils.get(member.guild.roles, name=role_name)
            if role:
                await member.add_roles(role)

        async def remove_roles(self, member):
            role_50 = discord.utils.get(member.guild.roles, name=self.ROLE_50_10)
            role_25 = discord.utils.get(member.guild.roles, name=self.ROLE_25_5)
            if role_50:
                await member.remove_roles(role_50)
            if role_25:
                await member.remove_roles(role_25)

        async def send_to_pomodoro(self, bot, embed):
            channel = bot.get_channel(self.POMODORO_CHANNEL_ID)
            if channel:
                await channel.send(embed=embed)
            else:
                print(f"Erreur: Le salon Pomodoro avec l'ID {self.POMODORO_CHANNEL_ID} n'a pas été trouvé.")

    # --- Classe SessionManager ---
    class SessionManager:
        def __init__(self):
            self.sessions = {}  # {'guild_id': {'50-10': set(), '25-5': set()}}

        def _ensure_guild_exists(self, guild_id):
            if guild_id not in self.sessions:
                self.sessions[guild_id] = {'50-10': set(), '25-5': set()}

        def join(self, member, mode):
            guild_id = member.guild.id
            self._ensure_guild_exists(guild_id)
            self.sessions[guild_id][mode].add(member.id)

        def leave(self, member):
            guild_id = member.guild.id
            self._ensure_guild_exists(guild_id)
            for mode in self.sessions[guild_id]:
                if member.id in self.sessions[guild_id][mode]:
                    self.sessions[guild_id][mode].remove(member.id)
                    break

        def get_participants(self, mode, guild):
            guild_id = guild.id
            self._ensure_guild_exists(guild_id)
            participant_ids = self.sessions[guild_id].get(mode, set())
            return [guild.get_member(user_id) for user_id in participant_ids if guild.get_member(user_id) is not None]

    # --- Classe TimerSession ---
    class TimerSession:
        def __init__(self, bot, guild, mode):
            self.bot = bot
            self.guild = guild
            self.mode = mode
            self.participants = set()
            self.is_working = True
            self.time_left = 50 if mode == '50-10' else 25
            self.session_manager = bot.session_manager
            self.role_manager = bot.role_manager
            self.timezone = timezone('Europe/Paris')

        async def run(self):
            while True:
                now = datetime.now(self.timezone)
                seconds_to_wait = 60 - now.second
                await asyncio.sleep(seconds_to_wait)

                if maintenance_mode:
                    continue

                participants = self.session_manager.get_participants(self.mode, self.guild)
                if not participants:
                    continue

                if self.is_working:
                    for member in participants:
                        self.save_time(member.id, self.mode, 1)
                    self.time_left -= 1
                else:
                    self.time_left -= 1

                if self.time_left == 0:
                    self.is_working = not self.is_working
                    duration = 50 if self.mode == '50-10' and self.is_working else (10 if self.mode == '50-10' else 5)
                    self.time_left = duration

                    embed = discord.Embed(
                        title=f"Pomodoro {'Travail' if self.is_working else 'Pause'} ({self.mode})",
                        description=f"Début de la session de {'travail' if self.is_working else 'pause'} de {duration} minutes.",
                        color=discord.Color.green() if self.is_working else discord.Color.blue()
                    )
                    mentions = ' '.join(member.mention for member in participants)
                    embed.add_field(name="Participants", value=mentions if mentions else "Aucun participant", inline=False)
                    await self.role_manager.send_to_pomodoro(self.bot, embed)

    # --- Initialisation des managers ---
    bot.role_manager = RoleManager()
    bot.session_manager = SessionManager()
    bot.timer_sessions = {} # {(guild_id, mode): TimerSession instance}

    # --- Fonctions de base de données ---
    def save_time(user_id, mode, minutes):
        user_data = db.get(User.user_id == user_id)
        if user_data:
            db.update({mode: user_data.get(mode, 0) + minutes}, User.user_id == user_id)
        else:
            db.insert({'user_id': user_id, mode: minutes})

    def get_user_times(user_id):
        return db.get(User.user_id == user_id)

    def get_leaderboard(mode=None):
        all_users = db.all()
        if mode:
            sorted_users = sorted([user for user in all_users if mode in user], key=lambda x: x.get(mode, 0), reverse=True)
        else:
            # Somme du temps dans les deux modes pour le leaderboard global
            sorted_users = sorted(all_users, key=lambda x: x.get('50-10', 0) + x.get('25-5', 0), reverse=True)
        return sorted_users[:10]

    def is_maintenance():
        maintenance_data = db.get(User.user_id == 0)
        return maintenance_data.get('maintenance', False) if maintenance_data else False

    def toggle_maintenance():
        global maintenance_mode
        maintenance_mode = not maintenance_mode
        if not db.get(User.user_id == 0):
            db.insert({'user_id': 0, 'maintenance': maintenance_mode})
        else:
            db.update({'maintenance': maintenance_mode}, User.user_id == 0)
        return maintenance_mode

    # --- Commandes du bot ---
    @bot.command(name='join')
    async def join_session(ctx, mode: str):
        if is_maintenance():
            await ctx.send("La commande est temporairement indisponible en mode maintenance.")
            return
        mode = mode.upper()
        if mode not in ['A', 'B']:
            await ctx.send("Mode invalide. Utilisez 'A' pour 50-10 ou 'B' pour 25-5.")
            return
        pomodoro_mode = '50-10' if mode == 'A' else '25-5'
        bot.session_manager.join(ctx.author, pomodoro_mode)
        await bot.role_manager.add_role(ctx.author, pomodoro_mode)
        await ctx.send(f"{ctx.author.mention} a rejoint la session Pomodoro {pomodoro_mode}.")

    @bot.command(name='leave')
    async def leave_session(ctx):
        if is_maintenance():
            await ctx.send("La commande est temporairement indisponible en mode maintenance.")
            return
        bot.session_manager.leave(ctx.author)
        await bot.role_manager.remove_roles(ctx.author)
        await ctx.send(f"{ctx.author.mention} a quitté la session Pomodoro.")

    @bot.command(name='time')
    async def show_time(ctx):
        if is_maintenance():
            await ctx.send("La commande est temporairement indisponible en mode maintenance.")
            return
        guild_timers = [timer for (guild_id, mode), timer in bot.timer_sessions.items() if guild_id == ctx.guild.id]
        if not guild_timers:
            await ctx.send("Aucune session Pomodoro active sur ce serveur.")
            return

        response = ""
        for timer in guild_timers:
            status = "Travail" if timer.is_working else "Pause"
            response += f"Mode {timer.mode}: {status} ({timer.time_left} min restantes)\n"
        await ctx.send(response)

    @bot.command(name='leaderboard')
    async def show_leaderboard(ctx, mode: str = None):
        if is_maintenance():
            await ctx.send("La commande est temporairement indisponible en mode maintenance.")
            return
        if mode and mode.upper() not in ['50-10', '25-5']:
            await ctx.send("Mode de leaderboard invalide. Utilisez '50-10' ou '25-5' (ou laissez vide pour le classement général).")
            return
        leaderboard = get_leaderboard(mode)
        if not leaderboard:
            await ctx.send("Aucun temps de travail enregistré pour le moment.")
            return

        title = "Leaderboard Pomodoro"
        if mode:
            title += f" ({mode})"
        embed = discord.Embed(title=title, color=discord.Color.gold())
        for i, user_data in enumerate(leaderboard):
            user = bot.get_user(user_data['user_id'])
            time_50 = user_data.get('50-10', 0)
            time_25 = user_data.get('25-5', 0)
            total_time = time_50 + time_25 if not mode else (time_50 if mode == '50-10' else time_25)
            embed.add_field(name=f"{i+1}. {user.name if user else 'Utilisateur inconnu'}", value=f"{total_time} minutes travaillées", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name='maintenance')
    @commands.is_owner()
    async def maintenance_toggle(ctx):
        global maintenance_mode
        maintenance_mode = toggle_maintenance()
        status = "activé" if maintenance_mode else "désactivé"
        await ctx.send(f"Le mode maintenance a été {status}.")

    @bot.command(name='helpadmin')
    @commands.is_owner()
    async def help_admin(ctx):
        embed = discord.Embed(title="Commandes Administrateur", color=discord.Color.red())
        embed.add_field(name="*maintenance", value="Activer/désactiver le mode maintenance.", inline=False)
        await ctx.send(embed=embed)

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CheckFailure):
            await ctx.send("Commande indisponible (maintenance ou permissions).")
        else:
            print(f"Erreur lors de l'exécution de la commande '{ctx.command.name}': {error}")
            await ctx.send("Une erreur est survenue lors de l'exécution de cette commande.")

    @bot.event
    async def on_ready():
        print(f'Connecté en tant que {bot.user.name}#{bot.user.discriminator}')
        await bot.change_presence(activity=discord.Game(name="Gérer vos Pomodoros"))

        for guild in bot.guilds:
            await bot.role_manager.setup_roles(guild)
            bot.timer_sessions[(guild.id, '50-10')] = TimerSession(bot, guild, '50-10')
            bot.timer_sessions[(guild.id, '25-5')] = TimerSession(bot, guild, '25-5')
            asyncio.create_task(bot.timer_sessions[(guild.id, '50-10')].run())
            asyncio.create_task(bot.timer_sessions[(guild.id, '25-5')].run())

    # --- Serveur Flask pour le keep-alive ---
    app = Flask(__name__)

    @app.route('/')
    def home():
        return "Bot is running."

    def run_flask():
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

    if __name__ == "__main__":
        flask_thread = Thread(target=run_flask)
        flask_thread.start()
        bot.run(TOKEN)