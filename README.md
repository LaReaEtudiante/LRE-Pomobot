Fichier : README.md

# LRE-Pomobot

**Version** : V3.26.10

Pomobot est un bot Discord pour gérer des sessions Pomodoro en deux modes, calées sur l’heure :

- **Mode A** : 50 min de travail (XX:00→XX:50) / 10 min de pause (XX:50→XX+1:00)  
- **Mode B** : 25 min de travail (XX:00→XX:25) → 5 min de pause (XX:25→XX:30) → 25 min de travail (XX:30→XX:55) → 5 min de pause (XX:55→XX+1:00)

Les sessions tournent en continu. Le bot calcule en direct la phase en cours et le temps restant à la seconde près.

---

## Prérequis

- Python 3.9+  
- Un serveur Discord et un bot configuré  
- Le token du bot dans une variable d’environnement `DISCORD_TOKEN`  

---

## Installation

```bash
git clone https://github.com/LaReaEtudiante/LRE-Pomobot.git
cd LRE-Pomobot
pip install -r requirements.txt



⸻

Configuration
	1.	Crée un fichier .env à la racine :

DISCORD_TOKEN=TON_TOKEN_ICI


	2.	Modifie settings.ini si nécessaire pour :
	•	channel_id : ID du canal où le bot poste les sessions
	•	prefix      : préfixe des commandes (défaut *)
	•	Rôles Pomodoro A & B

⸻

Commandes Étudiant

Commande	Description
*joinA	S’inscrire au mode A (50–10). Affiche la phase et le temps restant.
*joinB	S’inscrire au mode B (25–5–25–5). Affiche la phase et le temps restant.
*leave	Quitter sa session : comptabilise le temps exact passé (en s).
*time	Embed : temps restant avant la prochaine bascule pour A & B.
*status	Embed : latence, heure locale, phases A & B, temps restant, participants.
*stats	Embed : utilisateurs uniques, temps total / A / B (en min), moyenne.
*leaderboard	Embed : top 5 des contributeurs (minutes et secondes cumulées).
*help	Embed : liste de toutes les commandes.



⸻

Commandes Administrateur

Commande	Description
*maintenance	Activer/désactiver le mode maintenance
*set_channel	Définir le canal de sessions
*set_role_A	Définir le rôle Pomodoro A
*set_role_B	Définir le rôle Pomodoro B
*clear_stats	Réinitialiser toutes les statistiques pour le serveur
*help	Afficher l’aide complète



⸻

Architecture
	•	Boucle Pomodoro : @tasks.loop(minutes=1) calée sur les minutes 0/25/30/50/55 UTC
	•	Calcul de phase : utilitaire get_phase_and_remaining pour A & B à la seconde près
	•	Persistance : TinyDB stocke
	•	participants.json (join_time, mode)
	•	leaderboard.json (seconds cumulés par utilisateur)
	•	Messages : centralisés dans messages.py

⸻

Licence

Ce projet est sous Tous droits réservés.
Aucune partie de ce logiciel ne peut être utilisée, copiée, modifiée, distribuée ou transmise
sans l’autorisation écrite préalable de Tekilp.
Voir le fichier LICENSE pour les détails.

⸻

Contact

Pour toute demande d’autorisation ou question :
Discord : Tekilp#9533