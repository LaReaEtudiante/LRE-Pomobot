# database.py
from tinydb import TinyDB, Query
from datetime import datetime, timezone

User = Query()

# Fichier de stats
DB_STATS = TinyDB('leaderboard.json')
# Fichier de participants
DB_PART   = TinyDB('participants.json')

def ajouter_temps(user_id: int, guild_id: int, minutes: int):
    """Ajoute du temps de travail pour un utilisateur dans un serveur"""
    table = DB_STATS.table(str(guild_id))
    utilisateur = table.get(User.user_id == user_id)
    if utilisateur:
        table.update({'minutes': utilisateur['minutes'] + minutes},
                     User.user_id == user_id)
    else:
        table.insert({'user_id': user_id, 'minutes': minutes})

def recuperer_temps(user_id: int, guild_id: int) -> int:
    """Récupère le temps total (en minutes) d’un utilisateur pour un serveur"""
    table = DB_STATS.table(str(guild_id))
    utilisateur = table.get(User.user_id == user_id)
    return utilisateur['minutes'] if utilisateur else 0

def classement_top10(guild_id: int):
    """Top 10 des utilisateurs par temps cumulé"""
    table = DB_STATS.table(str(guild_id))
    users = table.all()
    users.sort(key=lambda x: x['minutes'], reverse=True)
    return [(u['user_id'], u['minutes']) for u in users[:10]]

# ———————— PARTICIPANTS ————————

def add_participant(user_id: int, guild_id: int):
    """Enregistre un participant avec horodatage UTC"""
    table = DB_PART.table(str(guild_id))
    now = datetime.now(timezone.utc).timestamp()
    if table.get(User.user_id == user_id):
        table.update({'join_time': now}, User.user_id == user_id)
    else:
        table.insert({'user_id': user_id, 'join_time': now})

def remove_participant(user_id: int, guild_id: int):
    """
    Supprime un participant et renvoie son horodatage d'entrée (timestamp),
    ou None s’il n’était pas présent
    """
    table = DB_PART.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    if not rec:
        return None
    join_ts = rec['join_time']
    table.remove(User.user_id == user_id)
    return join_ts

def get_all_participants(guild_id: int):
    """Retourne la liste des user_id inscrits au guild courant"""
    table = DB_PART.table(str(guild_id))
    return [r['user_id'] for r in table.all()]
