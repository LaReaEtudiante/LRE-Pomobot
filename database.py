import os
from tinydb import TinyDB, Query

# Chemin absolu pour sessions.json
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'sessions.json')

class Database:
    def __init__(self):
        self.db = TinyDB(DB_PATH)
        self.User = Query()

    def save_time(self, user_id: int, mode: str, minutes: int):
        user = self.db.get(self.User.user_id == user_id)
        if user:
            new_total = user.get(mode, 0) + minutes
            self.db.update({mode: new_total}, self.User.user_id == user_id)
        else:
            # On initialise tous les champs en une fois
            self.db.insert({
                'user_id': user_id,
                '50-10': minutes if mode == '50-10' else 0,
                '25-5': minutes if mode == '25-5' else 0,
                'maintenance': False
            })

    def get_user_times(self, user_id: int):
        user = self.db.get(self.User.user_id == user_id)
        if user:
            return {k: user.get(k, 0) for k in ['50-10', '25-5']}
        return {'50-10': 0, '25-5': 0}

    def get_leaderboard(self, mode: str = None):
        users = self.db.all()
        if mode:
            key = lambda x: x.get(mode, 0)
        else:
            key = lambda x: x.get('50-10', 0) + x.get('25-5', 0)
        sorted_users = sorted(users, key=key, reverse=True)[:10]
        return [(u['user_id'], key(u)) for u in sorted_users]

    def is_maintenance(self):
        record = self.db.get(self.User.user_id == 0)
        return bool(record and record.get('maintenance', False))

    def toggle_maintenance(self):
        record = self.db.get(self.User.user_id == 0)
        if record:
            new = not record.get('maintenance', False)
            self.db.update({'maintenance': new}, self.User.user_id == 0)
            return new
        else:
            self.db.insert({'user_id': 0, 'maintenance': True})
            return True
