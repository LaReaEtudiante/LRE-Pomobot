import os
from tinydb import TinyDB, Query

# Créer un chemin absolu pour le fichier sessions.json
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'sessions.json')


class Database:

    def __init__(self):
        self.db = TinyDB(DB_PATH)
        self.User = Query()

    def save_time(self, user_id: int, mode: str, minutes: int):
        """Sauvegarde le temps d'étude pour un utilisateur et un mode."""
        user = self.db.get(self.User.user_id == user_id)
        if user:
            new_total = user.get(mode, 0) + minutes
            self.db.update({mode: new_total}, self.User.user_id == user_id)
        else:
            self.db.insert({'user_id': user_id, mode: minutes})

    def get_user_times(self, user_id: int):
        """Récupère tous les temps d'un utilisateur."""
        user = self.db.get(self.User.user_id == user_id)
        if user:
            return user
        else:
            return {'50-10': 0, '25-5': 0}

    def get_leaderboard(self, mode: str):
        """Retourne les 10 meilleurs pour un mode donné."""
        users = self.db.all()
        sorted_users = sorted(users,
                              key=lambda x: x.get(mode, 0),
                              reverse=True)
        return [(u['user_id'], u.get(mode, 0)) for u in sorted_users[:10]]

    def get_global_leaderboard(self):
        """Retourne les 10 meilleurs en additionnant A et B."""
        users = self.db.all()
        sorted_users = sorted(
            users,
            key=lambda x: x.get('50-10', 0) + x.get('25-5', 0),
            reverse=True)
        return [(u['user_id'], u.get('50-10', 0) + u.get('25-5', 0))
                for u in sorted_users[:10]]