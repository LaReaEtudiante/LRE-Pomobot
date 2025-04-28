from tinydb import TinyDB, Query

User = Query()


def ajouter_temps(user_id: int, guild_id: int, temps: int):
    """Ajoute du temps de travail pour un utilisateur dans un serveur"""
    db = TinyDB('leaderboard.json')
    table = db.table(str(guild_id))

    utilisateur = table.get(User.user_id == user_id)
    if utilisateur:
        # Mise à jour si déjà existant
        nouveau_temps = utilisateur['minutes'] + temps
        table.update({'minutes': nouveau_temps}, User.user_id == user_id)
    else:
        # Sinon créer un nouvel enregistrement
        table.insert({'user_id': user_id, 'minutes': temps})


def recuperer_temps(user_id: int, guild_id: int):
    """Récupère le temps total de travail d'un utilisateur pour un serveur spécifique"""
    db = TinyDB('leaderboard.json')
    table = db.table(str(guild_id))
    utilisateur = table.get(User.user_id == user_id)
    if utilisateur:
        return utilisateur['minutes']
    else:
        return 0


def classement_top10(guild_id: int):
    """Récupère le top 10 des utilisateurs par temps de travail"""
    db = TinyDB('leaderboard.json')
    table = db.table(str(guild_id))

    users = table.all()
    users.sort(key=lambda x: x['minutes'], reverse=True)

    return [(u['user_id'], u['minutes']) for u in users[:10]]