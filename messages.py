# messages.py

from enum import Enum

class MsgColors(Enum):
    AQUA   = 0x33c6bb
    YELLOW = 0xFFD966
    RED    = 0xEA3546
    PURPLE = 0x6040b1

# ─── TEXTES SIMPLES ────────────────────────────────────────────────────────────
TEXT = {
    # Erreurs & aide
    "command_not_found":  "❓ Commande inconnue. Tapez `{prefix}help` pour voir la liste des commandes.",
    "maintenance_active": "⚠️ Le bot est en maintenance.",
    "missing_argument":   "❗ Argument manquant. Vérifiez la syntaxe de la commande.",
    "permission_denied":  "🚫 Permission refusée. Vous n'avez pas les droits requis.",
    "unexpected_error":   "❌ Erreur inattendue : {error}",
    "setup_incomplete":   "⚠️ Le bot n'est pas entièrement configuré. Utilisez `status` pour voir ce qui est manquant.",

    # Join / Leave
    "join_A":             "✅ {user_mention} a rejoint (mode A – 50-10).",
    "join_B":             "✅ {user_mention} a rejoint (mode B – 25-5).",
    "leave":              "👋 {user_mention} a quitté. +{minutes} min ajoutées.",

    # Commande *time
    "time_left":          "⌛ Phase suivante : {next_phase} – reste {minutes} min {seconds} s",

    # Admin / config
    "maintenance_toggle": "🔧 Mode maintenance {state}.",
    "set_channel":        "🔄 Canal défini sur {channel_mention}.",
    "set_role_A":         "🔄 Rôle A défini sur {role_mention}.",
    "set_role_B":         "🔄 Rôle B défini sur {role_mention}.",
    "clear_stats":        "♻️ Statistiques réinitialisées."
}

# ─── HELP EMBED ───────────────────────────────────────────────────────────────
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
                "`leaderboard` – top 5 général"
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

# ─── STATUS EMBED ─────────────────────────────────────────────────────────────
STATUS = {
    "title": "🔍 État du bot",
    "color": MsgColors.PURPLE.value,
    "fields": [
        {"name": "Latence",         "value_template": "{latency} ms",        "inline": True},
        {"name": "Heure (Lausanne)","value_template": "{local_time}",       "inline": True},
        {"name": "Session",         "value_template": "{session_status}",  "inline": False},
        {"name": "Fin prévue",      "value_template": "{ends_at}",         "inline": True},
        {"name": "Participants A",  "value_template": "{count_A}",         "inline": True},
        {"name": "Participants B",  "value_template": "{count_B}",         "inline": True},
    ]
}

# ─── STATS EMBED ──────────────────────────────────────────────────────────────
STATS = {
    "title": "📊 Stats Pomodoro",
    "color": MsgColors.AQUA.value,
    "fields": [
        {"name": "Utilisateurs uniques",      "value_template": "{unique_users}",       "inline": False},
        {"name": "Temps total (min)",         "value_template": "{total_minutes}",      "inline": False},
        {"name": "Moyenne/utilisateur (min)", "value_template": "{average_minutes:.1f}", "inline": False},
        {"name": "Temps total A (min)",       "value_template": "{total_A}",            "inline": False},
        {"name": "Temps total B (min)",       "value_template": "{total_B}",            "inline": False},
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