# messages.py

from enum import Enum

class MsgColors(Enum):
    AQUA   = 0x33c6bb
    YELLOW = 0xFFD966
    RED    = 0xEA3546
    PURPLE = 0x6040b1

# ─── HELP ────────────────────────────────────────────────────────────────────
HELP = {
    "title": "🛠️ Commandes Pomodoro",
    "color": MsgColors.PURPLE.value,
    "fields": [
        {
            "name": "Étudiant",
            "value": (
                "`joinA`       – rejoindre méthode A (50-10)\n"
                "`joinB`       – rejoindre méthode B (25-5)\n"
                "`leave`       – quitter\n"
                "`time`        – temps restant session\n"
                "`status`      – état du bot\n"
                "`stats`       – vos stats\n"
                "`leaderboard` – Top 5 général"
            ),
            "inline": False
        },
        {
            "name": "Administrateur",
            "value": (
                "`maintenance` – on/off\n"
                "`set_channel` – définir canal\n"
                "`set_role_A`  – définir rôle A\n"
                "`set_role_B`  – définir rôle B\n"
                "`clear_stats` – réinitialiser stats"
            ),
            "inline": False
        }
    ]
}

# ─── ERREURS ─────────────────────────────────────────────────────────────────
ERRORS = {
    "command_not_found": {
        "title": "❓ Commande inconnue",
        "description_template": "Tapez `{prefix}help` pour voir la liste des commandes.",
        "color": MsgColors.RED.value
    },
    "maintenance_active": {
        "title": "⚠️ Maintenance",
        "description_template": "Le bot est en maintenance.",
        "color": MsgColors.YELLOW.value
    },
    "missing_argument": {
        "title": "❗ Argument manquant",
        "description_template": "Vérifiez la syntaxe de la commande.",
        "color": MsgColors.RED.value
    },
    "permission_denied": {
        "title": "🚫 Permission refusée",
        "description_template": "Vous n'avez pas les droits requis.",
        "color": MsgColors.RED.value
    },
    "unexpected_error": {
        "title": "❌ Erreur inattendue",
        "description_template": "{error}",
        "color": MsgColors.RED.value
    }
}

# ─── MAINTENANCE ─────────────────────────────────────────────────────────────
MAINT_TOGGLE = {
    "title": "🔧 Mode Maintenance",
    "description_template": "Mode maintenance {state}.",
    "color": MsgColors.YELLOW.value
}

# ─── JOINDRE / QUITTER ────────────────────────────────────────────────────────
JOIN = {
    "A": {
        "description_template": "✅ {user_mention} a rejoint (mode A – 50-10).",
        "color": MsgColors.AQUA.value
    },
    "B": {
        "description_template": "✅ {user_mention} a rejoint (mode B – 25-5).",
        "color": MsgColors.AQUA.value
    },
    "ALREADY": {
        "description_template": "⚠️ Vous êtes déjà inscrit.",
        "color": MsgColors.YELLOW.value
    }
}

LEAVE = {
    "description_template": "👋 {user_mention} a quitté. +{minutes} min ajoutées.",
    "color": MsgColors.AQUA.value
}

# ─── TEMPS RESTANT ────────────────────────────────────────────────────────────
TIME_LEFT = {
    "title_template": "⏱️ Session {phase}",
    "description_template": "La {next_phase} commence dans **{minutes}** min et **{seconds}** sec.",
    "color": MsgColors.AQUA.value
}

# ─── STATUS ───────────────────────────────────────────────────────────────────
STATUS = {
    "title": "🔍 État du bot",
    "color": MsgColors.PURPLE.value,
    "fields": [
        {"name": "Latence",        "value_template": "{latency} ms",           "inline": True},
        {"name": "Heure (Lausanne)","value_template": "{local_time}",         "inline": True},
        {"name": "Session",        "value_template": "{session_status}",     "inline": False},
        {"name": "Fin prévue à",   "value_template": "{ends_at}",           "inline": True},
        {"name": "Participants A", "value_template": "{count_A}",           "inline": True},
        {"name": "Participants B", "value_template": "{count_B}",           "inline": True},
    ]
}

# ─── STATS ────────────────────────────────────────────────────────────────────
STATS = {
    "title": "📊 Stats Pomodoro",
    "color": MsgColors.AQUA.value,
    "fields": [
        {"name": "Utilisateurs uniques",      "value_template": "{unique_users}",        "inline": False},
        {"name": "Temps total (min)",         "value_template": "{total_minutes}",       "inline": False},
        {"name": "Moyenne/utilisateur (min)", "value_template": "{average_minutes:.1f}", "inline": False},
        {"name": "Temps total A (min)",       "value_template": "{total_A}",             "inline": False},
        {"name": "Temps total B (min)",       "value_template": "{total_B}",             "inline": False},
    ]
}

# ─── LEADERBOARD ──────────────────────────────────────────────────────────────
LEADERBOARD = {
    "title": "🏆 Leaderboard Pomodoro",
    "color": MsgColors.PURPLE.value,
    "entry_template": {
        "name_template": "#{rank} {username}",
        "value_template": "{minutes} min"
    }
}

# ─── ADMIN ─────────────────────────────────────────────────────────────────────
SET_CHANNEL = {
    "description_template": "🔄 Canal défini sur {channel_mention}.",
    "color": MsgColors.AQUA.value
}
SET_ROLE_A = {
    "description_template": "🔄 Rôle A défini sur {role_mention}.",
    "color": MsgColors.AQUA.value
}
SET_ROLE_B = {
    "description_template": "🔄 Rôle B défini sur {role_mention}.",
    "color": MsgColors.AQUA.value
}
CLEAR_STATS = {
    "description_template": "♻️ Statistiques réinitialisées.",
    "color": MsgColors.YELLOW.value
}

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
LOOP = {
    "start_template": "▶️ Début travail ({mode}, {duration} min) ! {role_mention}",
    "pause_template": "⏸️ Début pause ({mode}, {duration} min) ! {role_mention}"
}
