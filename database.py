import os
from tinydb import TinyDB, Query

# Créer un chemin absolu pour le fichier sessions.json
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'sessions.json')

db = TinyDB(DB_PATH)
User = Query()


def save_time(user_id: int, mode: str, minutes: int):
    """Sauvegarde le temps d'étude pour un utilisateur et un mode."""
    user = db.get(User.user_id == user_id)
    if user:
        new_total = user.get(mode, 0) + minutes
        db.update({mode: new_total}, User.user_id == user_id)
    else:
        db.insert({'user_id': user_id, mode: minutes})


def get_user_times(user_id: int):
    """Récupère tous les temps d'un utilisateur."""
    user = db.get(User.user_id == user_id)
    if user:
        return user
    else:
        return {'50-10': 0, '25-5': 0}


def get_leaderboard(mode: str):
    """Retourne les 10 meilleurs pour un mode donné."""
    users = db.all()
    sorted_users = sorted(users, key=lambda x: x.get(mode, 0), reverse=True)
    return [(u['user_id'], u.get(mode, 0)) for u in sorted_users[:10]]


def get_global_leaderboard():
    """Retourne les 10 meilleurs en additionnant A et B."""
    users = db.all()
    sorted_users = sorted(users,
                          key=lambda x: x.get('50-10', 0) + x.get('25-5', 0),
                          reverse=True)
    return [(u['user_id'], u.get('50-10', 0) + u.get('25-5', 0))
            for u in sorted_users[:10]]
