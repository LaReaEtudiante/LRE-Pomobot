# keep_alive.py

from flask import Flask
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    return "Je suis vivant !"

def run():
    # Render fournit son port dans l'ENV VAR PORT
    port = int(os.environ.get("PORT", 8080))
    # Le serveur Flask dev (même s'il n'est pas prévu pour la prod) suffit
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
