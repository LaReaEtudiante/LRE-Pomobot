from tinydb import TinyDB, Query

# On crée la base de données dans un fichier JSON
db = TinyDB('db.json')
User = Query()


def ajouter_temps(user_id: int, temps: int):
    """Ajoute du temps de travail pour un utilisateur"""
    utilisateur = db.get(User.user_id == user_id)
    if utilisateur:
        # Mise à jour si déjà existant
        nouveau_temps = utilisateur['temps'] + temps
        db.update({'temps': nouveau_temps}, User.user_id == user_id)
    else:
        # Sinon créer un nouvel enregistrement
        db.insert({'user_id': user_id, 'temps': temps})


def recuperer_temps(user_id: int):
    """Récupère le temps total de travail d'un utilisateur"""
    utilisateur = db.get(User.user_id == user_id)
    if utilisateur:
        return utilisateur['temps']
    else:
        return 0


def classement_top10(guild_id):
    db = TinyDB('leaderboard.json')
    table = db.table(str(guild_id))

    users = table.all()
    users.sort(key=lambda x: x['minutes'], reverse=True)

    return [(u['user_id'], u['minutes']) for u in users[:10]]
