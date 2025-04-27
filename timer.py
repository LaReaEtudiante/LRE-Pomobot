import asyncio
import datetime
import pytz

class TimerSession:
    def __init__(self, name: str, work_duration: int, break_duration: int):
        self.name = name
        self.work_duration = work_duration
        self.break_duration = break_duration
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
            to_sleep = 60 - now.second
            await asyncio.sleep(to_sleep)

            participants = get_participants(self.name)
            if not participants:
                continue

            self.time_left -= 1
            if self.time_left <= 0:
                self.is_working = not self.is_working
                self.time_left = self.work_duration if self.is_working else self.break_duration

                state = "Session de travail" if self.is_working else "Pause"
                mentions = ' '.join(m.mention for m in participants)
                embed = discord.Embed(
                    title=f"⏰ {state} {self.name}",
                    description=f"{mentions}\nParticipants: {len(participants)}",
                    color=discord.Color.purple()
                )
                await channel.send(embed=embed)