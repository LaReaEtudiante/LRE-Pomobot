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


def classement_top10():
    """Retourne le top 10 des utilisateurs par temps travaillé"""
    utilisateurs = db.all()
    utilisateurs = sorted(utilisateurs, key=lambda x: x['temps'], reverse=True)
    return utilisateurs[:10]
