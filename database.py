from tinydb import TinyDB, Query
from datetime import datetime, timezone

DB_STATS = TinyDB('leaderboard.json')
DB_PART  = TinyDB('participants.json')
User     = Query()

def ajouter_temps(user_id: int, guild_id: int, minutes: int, mode: str):
    """
    Ajoute 'minutes' au total et au mode (A ou B) pour user_id dans guild_id.
    """
    table = DB_STATS.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    if rec:
        table.update({'total': rec['total'] + minutes},                          User.user_id == user_id)
        if mode == 'A':
            table.update({'A': rec.get('A', 0) + minutes},                      User.user_id == user_id)
        else:
            table.update({'B': rec.get('B', 0) + minutes},                      User.user_id == user_id)
    else:
        table.insert({
            'user_id': user_id,
            'total':   minutes,
            'A':       minutes if mode == 'A' else 0,
            'B':       minutes if mode == 'B' else 0
        })

def get_user_stats(user_id: int, guild_id: int) -> dict:
    """
    Retourne {user_id, total, A, B} pour l'utilisateur.
    """
    table = DB_STATS.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    if not rec:
        return {'user_id': user_id, 'total': 0, 'A': 0, 'B': 0}
    return rec

def classement_top5(guild_id: int) -> list:
    """
    Top 5 général sur 'total'.
    """
    table = DB_STATS.table(str(guild_id))
    lst = table.all()
    lst.sort(key=lambda x: x['total'], reverse=True)
    return lst[:5]

def classement_top5_modeA(guild_id: int) -> list:
    """
    Top 5 mode A.
    """
    table = DB_STATS.table(str(guild_id))
    lst = table.all()
    lst.sort(key=lambda x: x.get('A', 0), reverse=True)
    return lst[:5]

def classement_top5_modeB(guild_id: int) -> list:
    """
    Top 5 mode B.
    """
    table = DB_STATS.table(str(guild_id))
    lst = table.all()
    lst.sort(key=lambda x: x.get('B', 0), reverse=True)
    return lst[:5]

# — PARTICIPANTS — #

def add_participant(user_id: int, guild_id: int, mode: str):
    """
    Enregistre ou met à jour join_time (timestamp UTC) et mode ('A'/'B').
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
    Supprime un participant et renvoie (join_time, mode) ou (None, None).
    """
    table = DB_PART.table(str(guild_id))
    rec = table.get(User.user_id == user_id)
    if not rec:
        return None, None
    jt   = rec['join_time']
    md   = rec.get('mode')
    table.remove(User.user_id == user_id)
    return jt, md

def get_all_participants(guild_id: int) -> list:
    """
    Renvoie liste de (user_id, mode) pour tous les inscrits.
    """
    table = DB_PART.table(str(guild_id))
    return [(r['user_id'], r['mode']) for r in table.all()]
