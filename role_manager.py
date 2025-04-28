import discord

# IDs des rôles pour les modes 50-10 et 25-5
ROLE_50_10_NAME = "50-10"
ROLE_25_5_NAME = "25-5"

# ID du salon Pomodoro
POMODORO_CHANNEL_ID = 1114960555004735558


async def setup_roles(bot):
    """Créer les rôles 50-10 et 25-5 s'ils n'existent pas."""
    for guild in bot.guilds:
        existing_roles = {role.name: role for role in guild.roles}

        if ROLE_50_10_NAME not in existing_roles:
            await guild.create_role(name=ROLE_50_10_NAME,
                                    color=discord.Color.blue())
            print(f"Rôle {ROLE_50_10_NAME} créé.")

        if ROLE_25_5_NAME not in existing_roles:
            await guild.create_role(name=ROLE_25_5_NAME,
                                    color=discord.Color.green())
            print(f"Rôle {ROLE_25_5_NAME} créé.")


async def assign_role(member, mode):
    """Assigner un rôle selon le mode choisi."""
    role_name = ROLE_50_10_NAME if mode == '50-10' else ROLE_25_5_NAME
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role:
        await member.add_roles(role)


async def remove_role(member, mode):
    """Enlever un rôle selon le mode quitté."""
    role_name = ROLE_50_10_NAME if mode == '50-10' else ROLE_25_5_NAME
    role = discord.utils.get(member.guild.roles, name=role_name)
    if role:
        await member.remove_roles(role)


async def send_to_pomodoro_channel(bot, embed):
    """Envoie un embed au salon pomodoro."""
    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)
    else:
        print(
            f"Erreur : Impossible de trouver le salon pomodoro avec l'ID {POMODORO_CHANNEL_ID}."
        )


class RoleManager:

    async def add_role(self, member, mode):
        await assign_role(member, mode)

    async def remove_roles(self, member):
        for role in member.roles:
            if role.name in [ROLE_50_10_NAME, ROLE_25_5_NAME]:
                await member.remove_roles(role)