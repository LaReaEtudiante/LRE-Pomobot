import discord
import datetime
from role_manager import assign_role, remove_role, send_to_pomodoro_channel

# Système mémoire temporaire pour les sessions (RAM uniquement)
sessions = {'50-10': set(), '25-5': set()}


async def join_session(bot, ctx, mode):
    """Ajouter un membre à une session."""
    mode = mode.lower()
    if mode not in sessions:
        await ctx.send("❌ Mode invalide. Utilisez `50-10` ou `25-5`.")
        return

    # Vérifie si déjà inscrit dans un autre mode
    other_mode = '25-5' if mode == '50-10' else '50-10'
    if ctx.author.id in sessions[other_mode]:
        await ctx.send(
            "❌ Tu es déjà inscrit dans l'autre mode. Utilise `*leave` avant.")
        return

    if ctx.author.id in sessions[mode]:
        await ctx.send("⚠️ Tu es déjà dans ce mode.")
        return

    sessions[mode].add(ctx.author.id)
    await assign_role(ctx.author, mode)

    embed = discord.Embed(
        title="🎯 Session Rejointe",
        description=
        f"{ctx.author.mention} a rejoint la session **{mode.upper()}** !",
        color=0x33c6bb)
    await send_to_pomodoro_channel(bot, embed)


async def leave_session(bot, ctx):
    """Retirer un membre de sa session."""
    found = False
    for mode in sessions:
        if ctx.author.id in sessions[mode]:
            sessions[mode].remove(ctx.author.id)
            await remove_role(ctx.author, mode)
            found = True

            embed = discord.Embed(
                title="👋 Session quittée",
                description=
                f"{ctx.author.mention} a quitté la session...",
                color=0xff6f6f)
            await send_to_pomodoro_channel(bot, embed)

    if not found:
        await ctx.send("❌ Tu n'es dans aucune session.")
    else:
        await ctx.send("✅ Tu as bien quitté ta session.")


async def send_to_pomodoro_channel(bot, embed):
    """Envoie un embed au salon Pomodoro."""
    channel = bot.get_channel(POMODORO_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)
    else:
        print(f"Erreur: Salon Pomodoro ({POMODORO_CHANNEL_ID}) non trouvé !")


def get_participants(mode):
    """Retourne la liste des participants d'une session."""
    return sessions.get(mode, set())


def get_session_info():
    """Retourne les informations de toutes les sessions."""
    now = datetime.datetime.now()
    info = "📊 Infos Sessions Pomodoro\n"
    for mode, participants in sessions.items():
        info += f"- **{mode.upper()}**: {len(participants)} participant(s)\n"
    info += f"⏰ Mise à jour : {now.strftime('%H:%M:%S')}"
    return info