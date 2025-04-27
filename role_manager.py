import discord

class RoleManager:
    # Constants exposés sur l'instance
    ROLE_50_10 = '50-10'
    ROLE_25_5 = '25-5'
    POMODORO_CHANNEL_ID = 1365678171671892018

    async def setup_roles(self, bot):
        for guild in bot.guilds:
            existing = {r.name for r in guild.roles}
            if self.ROLE_50_10 not in existing:
                await guild.create_role(
                    name=self.ROLE_50_10,
                    color=discord.Color.blue()
                )
            if self.ROLE_25_5 not in existing:
                await guild.create_role(
                    name=self.ROLE_25_5,
                    color=discord.Color.green()
                )

    async def add_role(self, member: discord.Member, mode: str):
        role_name = self.ROLE_50_10 if mode == self.ROLE_50_10 else self.ROLE_25_5
        role = discord.utils.get(member.guild.roles, name=role_name)
        if role:
            await member.add_roles(role)

    async def remove_roles(self, member: discord.Member):
        for role_name in (self.ROLE_50_10, self.ROLE_25_5):
            role = discord.utils.get(member.guild.roles, name=role_name)
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
