import datetime
from role_manager import assign_role, remove_role, send_to_pomodoro_channel

# Système mémoire temporaire pour les sessions (RAM uniquement)
sessions = {
    '50-10': set(),
    '25-5': set()
}

async def join_session(bot, ctx, mode):
    """Ajouter un membre à une session."""
    mode = mode.lower()
    if mode not in sessions:
        await ctx.send("❌ Mode invalide. Utilisez `50-10` ou `25-5`.")
        return

    # Vérifie si déjà inscrit dans un autre mode
    other_mode = '25-5' if mode == '50-10' else '50-10'
    if ctx.author.id in sessions[other_mode]:
        await ctx.send("❌ Tu es déjà inscrit dans l'autre mode. Utilise `*leave` avant.")
        return

    if ctx.author.id in sessions[mode]:
        await ctx.send("⚠️ Tu es déjà dans ce mode.")
        return

    sessions[mode].add(ctx.author.id)
    await assign_role(ctx.author, mode)

    embed = discord.Embed(
        title="🎯 Session Rejointe",
        description=f"{ctx.author.mention} a rejoint la session **{mode.upper()}** !",
        color=0x33c6bb
    )
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
                description=f"{ctx.author.mention} a quitté la session **{mode.upper()}**.",
                color=0xEA3546
            )
            await send_to_pomodoro_channel(bot, embed)
            break

    if not found:
        await ctx.send("⚠️ Tu n'es inscrit dans aucune session.")
