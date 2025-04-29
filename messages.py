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
                "`joinA`       – rejoindre A (50-10)\n"
                "`joinB`       – rejoindre B (25-5)\n"
                "`leave`       – quitter\n"
                "`time`        – temps restant\n"
                "`status`      – état du bot\n"
                "`stats`       – vos stats\n"
                "`leaderboard` – top 5"
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
                "`clear_stats` – vider stats"
            ),
            "inline": False
        }
    ]
}

# ─── ERREURS ─────────────────────────────────────────────────────────────────
ERRORS = {
    "command_not_found": {
        "title": "❓ Commande inconnue",
        "description": "Tapez `{prefix}help` pour voir la liste des commandes.",
        "color": MsgColors.RED.value
    },
    "maintenance_active": {
        "title": "⚠️ Maintenance",
        "description": "Le bot est en maintenance.",
        "color": MsgColors.YELLOW.value
    },
    "missing_argument": {
        "title": "❗ Argument manquant",
        "description": "Vérifiez la syntaxe de la commande.",
        "color": MsgColors.RED.value
    },
    "permission_denied": {
        "title": "🚫 Permission refusée",
        "description": "Vous n'avez pas les droits requis pour cette commande.",
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
    "color": MsgColors.YELLOW.value,
    "description_template": "Mode maintenance {state}."
}

# ─── JOINDRE / QUITTER ────────────────────────────────────────────────────────
JOIN = {
    "A": {
        "description_template": "{user_mention} a rejoint (mode A – 50-10).",
        "color": MsgColors.AQUA.value
    },
    "B": {
        "description_template": "{user_mention} a rejoint (mode B – 25-5).",
        "color": MsgColors.AQUA.value
    }
}

LEAVE = {
    "description_template": "{user_mention} a quitté. +{minutes} min ajoutées.",
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
        {"name": "Latence",          "value_template": "{latency} ms",         "inline": True},
        {"name": "Heure (Lausanne)", "value_template": "{local_time}",       "inline": True},
        {"name": "Session",          "value_template": "{session_status}", "inline": False}
    ]
}

# ─── STATS ────────────────────────────────────────────────────────────────────
STATS = {
    "title": "📊 Stats Pomodoro",
    "color": MsgColors.AQUA.value,
    "fields": [
        {"name": "Utilisateurs uniques",         "value_template": "{unique_users}",        "inline": False},
        {"name": "Temps total (min)",            "value_template": "{total_minutes}",       "inline": False},
        {"name": "Moyenne/utilisateur (min)",    "value_template": "{average_minutes:.1f}", "inline": False}
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
    "description_template": "Canal défini sur {channel_mention}.",
    "color": MsgColors.AQUA.value
}
SET_ROLE_A = {
    "description_template": "Rôle A défini sur {role_mention}.",
    "color": MsgColors.AQUA.value
}
SET_ROLE_B = {
    "description_template": "Rôle B défini sur {role_mention}.",
    "color": MsgColors.AQUA.value
}
CLEAR_STATS = {
    "description_template": "Statistiques réinitialisées.",
    "color": MsgColors.YELLOW.value
}

# ─── BOUCLE POMODORO ──────────────────────────────────────────────────────────
LOOP = {
    "start_template": "Début travail ({mode}, {duration} min) ! {role_mention}",
    "pause_template": "Début pause ({mode}, {duration} min) ! {role_mention}"
}
