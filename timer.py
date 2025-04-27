import asyncio
import datetime
import pytz
import discord

class TimerSession:
    def __init__(self, name: str, work_duration: int, break_duration: int):
        self.name = name
        self.work_duration = work_duration  # en minutes
        self.break_duration = break_duration  # en minutes
        self.is_working = True
        self.time_left = work_duration

    async def run(self, bot, channel_id, get_participants):
        tz = pytz.timezone('Europe/Paris')
        await bot.wait_until_ready()
        channel = bot.get_channel(channel_id)
        if not channel:
            return

        while True:
            now = datetime.datetime.now(tz)
            await asyncio.sleep(60 - now.second)

            participants = get_participants(self.name)
            if not participants:
                continue

            self.time_left -= 1
            # Sauvegarde du temps de travail
            if self.is_working:
                from database import Database
                db = Database()
                # on compte 1 minute de plus pour chaque participant
                for member in participants:
                    db.save_time(member.id, self.name, 1)

            if self.time_left <= 0:
                self.is_working = not self.is_working
                self.time_left = (self.work_duration if self.is_working
                                  else self.break_duration)

                state = "Session de travail" if self.is_working else "Pause"
                mentions = " ".join(m.mention for m in participants)
                embed = discord.Embed(
                    title=f"⏰ {state} {self.name}",
                    description=f"{mentions}\nParticipants : {len(participants)}",
                    color=discord.Color.purple()
                )
                await channel.send(embed=embed)
