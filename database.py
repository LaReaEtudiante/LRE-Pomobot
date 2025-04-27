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
                        self.db.insert({'user_id': user_id, mode: minutes, '50-10': 0, '25-5': 0, 'maintenance': False})

                def get_user_times(self, user_id: int):
                    user = self.db.get(self.User.user_id == user_id)
                    if user:
                        return {k: user.get(k, 0) for k in ['50-10', '25-5']}
                    return {'50-10': 0, '25-5': 0}

                def get_leaderboard(self, mode: str = None):
                    users = self.db.all()
                    key = (lambda x: x.get(mode, 0)) if mode else (lambda x: x.get('50-10',0)+x.get('25-5',0))
                    sorted_users = sorted(users, key=key, reverse=True)
                    top = sorted_users[:10]
                    return [(u['user_id'], key(u)) for u in top]

                # Maintenance
                def is_maintenance(self):
                    # On garde une seule ligne avec user_id = 0 pour l'état global
                    record = self.db.get(self.User.user_id == 0)
                    return record and record.get('maintenance', False)

                def toggle_maintenance(self):
                    record = self.db.get(self.User.user_id == 0)
                    if record:
                        new = not record.get('maintenance', False)
                        self.db.update({'maintenance': new}, self.User.user_id == 0)
                        return new
                    else:
                        self.db.insert({'user_id': 0, 'maintenance': True})
                        return True