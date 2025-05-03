# messages.py

from enum import Enum

class MsgColors(Enum):
    AQUA   = 0x33c6bb
    YELLOW = 0xFFD966
    RED    = 0xEA3546
    PURPLE = 0x6040b1

# ─── TEXTES SIMPLES ────────────────────────────────────────────────────────────
TEXT = {
    "command_not_found":  "❓ Commande inconnue. Tapez `{prefix}help` pour voir la liste des commandes.",
    "maintenance_active": "⚠️ Le bot est en maintenance.",
    "missing_argument":   "❗ Argument manquant. Vérifiez la syntaxe de la commande.",
    "permission_denied":  "🚫 Permission refusée. Vous n'avez pas les droits requis.",
    "unexpected_error":   "❌ Erreur inattendue : {error}",

    "already_joined":     "⚠️ Vous êtes déjà inscrit.",
    "not_registered":     "⚠️ Vous n'étiez pas inscrit.",
    "join_A":             "✅ {user_mention} a rejoint (mode A – 50-10).",
    "join_B":             "✅ {user_mention} a rejoint (mode B – 25-5).",
    "leave":              "👋 {user_mention} a quitté. +{minutes} min ajoutées.",

    "maintenance_toggle": "🔧 Mode maintenance {state}.",
    "set_channel":        "🔄 Canal défini sur {channel_mention}.",
    "set_role_A":         "🔄 Rôle A défini sur {role_mention}.",
    "set_role_B":         "🔄 Rôle B défini sur {role_mention}.",
    "clear_stats":        "♻️ Statistiques réinitialisées.",
    "setup_incomplete":   "❌ Configuration incomplète. Veuillez lancer `*set_channel`, `*set_role_A` et `*set_role_B`."
}

# ─── HELP EMBED ───────────────────────────────────────────────────────────────
HELP = {
    "title": "🛠️ Commandes Pomodoro",
    "color": MsgColors.PURPLE.value,
    "fields": [
        {
            "name": "Étudiant",
            "value": (
                "`joinA`       – rejoindre le mode A (50-min travail / 10-min pause)\n"
                "`joinB`       – rejoindre le mode B (25-5-25-5)\n"
                "`leave`       – quitter la session en cours\n"
                "`me`          – voir vos stats détaillées\n"
                "`status`      – voir l’état global du bot\n"
                "`stats`       – statistiques du serveur\n"
                "`leaderboard` – top 5 des contributeurs"
            ),
            "inline": False
        },
        {
            "name": "Administrateur",
            "value": (
                "`maintenance` – activer/désactiver maintenance\n"
                "`set_channel` – définir le salon Pomodoro\n"
                "`set_role_A`  – définir ou créer le rôle A\n"
                "`set_role_B`  – définir ou créer le rôle B\n"
                "`clear_stats` – réinitialiser toutes les stats\n"
                "`update`      – pull GitHub & redémarrer le bot"
            ),
            "inline": False
        }
    ]
}

# ─── STATUS EMBED ─────────────────────────────────────────────────────────────
STATUS = {
    "title": "🔍 État du bot",
    "color": MsgColors.PURPLE.value,
    "fields": [
        {"name": "Latence",          "value_template": "{latency} ms",   "inline": True},
        {"name": "Heure (Lausanne)", "value_template": "{local_time}",    "inline": True},
        {"name": "Mode A",           "value_template": "{mode_A}",       "inline": False},
        {"name": "Restant A",        "value_template": "{remaining_A}",  "inline": True},
        {"name": "Mode B",           "value_template": "{mode_B}",       "inline": False},
        {"name": "Restant B",        "value_template": "{remaining_B}",  "inline": True},
        {"name": "Version Git",      "value_template": "{version}",      "inline": True},
    ]
}

# ─── STATS EMBED ──────────────────────────────────────────────────────────────
STATS = {
    "title": "📊 Stats Pomodoro",
    "color": MsgColors.AQUA.value,
    "fields": [
        {"name": "Utilisateurs uniques",      "value_template": "{unique_users}",      "inline": False},
        {"name": "Temps total (min)",         "value_template": "{total_minutes}",     "inline": False},
        {"name": "Moyenne/utilisateur (min)", "value_template": "{average_minutes:.1f}","inline": False}
    ]
}

# ─── LEADERBOARD EMBED ────────────────────────────────────────────────────────
LEADERBOARD = {
    "title": "🏆 Leaderboard Pomodoro",
    "color": MsgColors.PURPLE.value,
    "entry_template": {
        "name_template": "#{rank} {username}",
        "value_template": "{minutes} min"
    }
}
