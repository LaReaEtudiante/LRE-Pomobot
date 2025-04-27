                                import discord

                                ROLE_50_10 = '50-10'
                                ROLE_25_5 = '25-5'
                                POMODORO_CHANNEL_ID = 1365678171671892018

                                class RoleManager:
                                    async def setup_roles(self, bot):  # bot: commands.Bot ou discord.Client
                                        for guild in bot.guilds:
                                            names = {r.name for r in guild.roles}
                                            if ROLE_50_10 not in names:
                                                await guild.create_role(name=ROLE_50_10, color=discord.Color.blue())
                                            if ROLE_25_5 not in names:
                                                await guild.create_role(name=ROLE_25_5, color=discord.Color.green())

                                    async def add_role(self, member: discord.Member, mode: str):
                                        role_name = ROLE_50_10 if mode == '50-10' else ROLE_25_5
                                        role = discord.utils.get(member.guild.roles, name=role_name)
                                        if role:
                                            await member.add_roles(role)

                                    async def remove_roles(self, member: discord.Member):
                                        for mode in (ROLE_50_10, ROLE_25_5):
                                            role = discord.utils.get(member.guild.roles, name=mode)
                                            if role in member.roles:
                                                await member.remove_roles(role)

                                    async def send_to_pomodoro(self, bot, embed: discord.Embed):
                                        for guild in bot.guilds:
                                            channel = discord.utils.get(guild.text_channels, id=POMODORO_CHANNEL_ID)
                                            if channel:
                                                await channel.send(embed=embed)