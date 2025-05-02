# LRE-Pomobot

**Version** : V4.0.3

Pomobot est un bot Discord pour gérer des sessions Pomodoro en deux modes, calées sur l’heure :

- **Mode A** : 50 min de travail (XX:00→XX:50) / 10 min de pause (XX:50→XX+1:00)  
- **Mode B** : 25 min de travail (XX:00→XX:25) → 5 min de pause (XX:25→XX:30) → 25 min de travail (XX:30→XX:55) → 5 min de pause (XX:55→XX+1:00)

Les sessions tournent en continu. Le bot calcule en direct la phase en cours et le temps restant à la seconde près.

---

## Prérequis

- Python 3.9+  
- Un serveur Discord et un bot configuré  
- Le token du bot dans une variable d’environnement `DISCORD_TOKEN`  

---

## Installation

```bash
git clone https://github.com/LaReaEtudiante/LRE-Pomobot.git
cd LRE-Pomobot
pip install -r requirements.txt
