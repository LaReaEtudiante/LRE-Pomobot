import asyncio
import datetime
import pytz


class TimerSession:

    def __init__(self, name, work_duration, break_duration):
        self.name = name
        self.work_duration = work_duration  # minutes
        self.break_duration = break_duration  # minutes
        self.is_working = True
        self.time_left = work_duration

    async def run(self, bot, channel_id, get_participants):
        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"Erreur: Salon {channel_id} non trouvé.")
            return

        timezone = pytz.timezone('Europe/Zurich')

        while True:
            now = datetime.datetime.now(timezone)
            seconds_until_next_minute = 60 - now.second
            await asyncio.sleep(seconds_until_next_minute)

            if get_participants(
                    self.name):  # Vérifie s'il y a des utilisateurs
                self.time_left -= 1

                if self.time_left <= 0:
                    self.is_working = not self.is_working
                    self.time_left = self.work_duration if self.is_working else self.break_duration

                    participants = get_participants(self.name)
                    if participants:
                        mentions = ' '.join(p.mention for p in participants)
                        state = "Session de travail" if self.is_working else "Pause"
                        await channel.send(
                            f"⏰ **{state} {self.name}**\n{mentions}\n({len(participants)} participants)"
                        )
            else:
                # Pas d'utilisateurs -> timer continue sans spammer
                continue