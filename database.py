# database.py

from tinydb import TinyDB, Query
from datetime import datetime, timezone

User = Query()

# 2 bases de données : stats et participants
DB_STATS = TinyDB('leaderboard.json')
DB_PART   = TinyDB('participants.json')


def ajouter_temps(user_id: int, guild_id: int, minutes: int):
    """Ajoute du temps de travail pour un utilisateur dans un serveur."""
    table = DB_STATS.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    if rec:
        table.update({'minutes': rec['minutes'] + minutes},
                     User.user_id == user_id)
    else:
        table.insert({'user_id': user_id, 'minutes': minutes})


def recuperer_temps(user_id: int, guild_id: int) -> int:
    """Récupère le temps total (en minutes) d’un utilisateur pour un serveur."""
    table = DB_STATS.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    return rec['minutes'] if rec else 0


def classement_top10(guild_id: int):
    """Top 10 des utilisateurs par temps cumulé."""
    table = DB_STATS.table(str(guild_id))
    users = table.all()
    users.sort(key=lambda x: x['minutes'], reverse=True)
    return [(u['user_id'], u['minutes']) for u in users[:10]]


# — PARTICIPANTS — #

def add_participant(user_id: int, guild_id: int, mode: str):
    """
    Enregistre un participant dans DB_PART avec :
      - join_time : timestamp UTC
      - mode : 'A' ou 'B'
    """
    table = DB_PART.table(str(guild_id))
    now = datetime.now(timezone.utc).timestamp()
    rec = table.get(User.user_id == user_id)
    if rec:
        table.update({'join_time': now, 'mode': mode},
                     User.user_id == user_id)
    else:
        table.insert({'user_id': user_id, 'join_time': now, 'mode': mode})


def remove_participant(user_id: int, guild_id: int):
    """
    Supprime un participant et renvoie (join_time, mode) ou (None, None)
    s’il n’était pas inscrit.
    """
    table = DB_PART.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    if not rec:
        return None, None
    join_ts = rec['join_time']
    mode    = rec.get('mode')
    table.remove(User.user_id == user_id)
    return join_ts, mode


def get_all_participants(guild_id: int):
    """
    Retourne la liste des tuples (user_id, mode) inscrits pour un serveur.
    """
    table = DB_PART.table(str(guild_id))
    return [(r['user_id'], r['mode']) for r in table.all()]
