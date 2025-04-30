from tinydb import TinyDB, Query
from datetime import datetime, timezone

User = Query()

# Fichiers TinyDB pour séparer les stats A et B
DB_STATS_A = TinyDB('leaderboard_A.json')
DB_STATS_B = TinyDB('leaderboard_B.json')
DB_PART    = TinyDB('participants.json')

def ajouter_temps_A(user_id: int, guild_id: int, minutes: int):
    """Ajoute du temps de travail en mode A pour un utilisateur."""
    table = DB_STATS_A.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    if rec:
        table.update({'minutes': rec['minutes'] + minutes}, User.user_id == user_id)
    else:
        table.insert({'user_id': user_id, 'minutes': minutes})

def ajouter_temps_B(user_id: int, guild_id: int, minutes: int):
    """Ajoute du temps de travail en mode B pour un utilisateur."""
    table = DB_STATS_B.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    if rec:
        table.update({'minutes': rec['minutes'] + minutes}, User.user_id == user_id)
    else:
        table.insert({'user_id': user_id, 'minutes': minutes})

def classement_top10(guild_id: int):
    """Top 10 combiné (A+B) des utilisateurs par minutes cumulées."""
    ta = {r['user_id']: r['minutes'] for r in DB_STATS_A.table(str(guild_id)).all()}
    tb = {r['user_id']: r['minutes'] for r in DB_STATS_B.table(str(guild_id)).all()}
    total = {uid: ta.get(uid, 0) + tb.get(uid, 0) for uid in set(ta) | set(tb)}
    top = sorted(total.items(), key=lambda x: x[1], reverse=True)[:10]
    return top

# — PARTICIPANTS — #

def add_participant(user_id: int, guild_id: int, mode: str):
    """
    Enregistre un participant avec horodatage UTC et son mode ('A' ou 'B').
    """
    table = DB_PART.table(str(guild_id))
    now = datetime.now(timezone.utc).timestamp()
    rec = table.get(User.user_id == user_id)
    if rec:
        table.update({'join_time': now, 'mode': mode}, User.user_id == user_id)
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
    Retourne la liste des (user_id, mode) inscrits pour un serveur.
    """
    table = DB_PART.table(str(guild_id))
    return [(r['user_id'], r['mode']) for r in table.all()]
