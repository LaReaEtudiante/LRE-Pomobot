from typing import Dict, Set, List
import discord
from role_manager import ROLE_50_10, ROLE_25_5

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Set[int]] = {'50-10': set(), '25-5': set()}

    async def join(self, member: discord.Member, mode: str):
        mode = mode.lower()
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

    def get_participants(self, mode: str, guild: discord.Guild) -> List[discord.Member]:
        return [guild.get_member(uid) for uid in self.sessions[mode] if guild.get_member(uid)]