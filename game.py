"""
Mafia o'yinining "miyasi". Har bir guruh (chat_id) uchun alohida Game
obyekti bor. Barcha holat xotirada saqlanadi (RAM) — Render qayta ishga
tushsa o'yin qayta boshlanadi, lekin tarix statistika.db'da qoladi.
"""
import random
import time
import sqlite3

DB_PATH = "stats.db"

ROLE_NAMES = {
    "mafia": "🔫 Mafiya",
    "doctor": "💉 Doktor",
    "detective": "🕵️ Detektiv",
    "civilian": "👤 Tinch aholi",
}

ROLE_DESC = {
    "mafia": "Har kecha bitta odamni yo'q qilasan. Kunduzi o'zingni tinch aholidek tut.",
    "doctor": "Har kecha bitta odamni (o'zingni ham) o'limdan qutqarasan.",
    "detective": "Har kecha bitta odamni tekshirib, u mafiyami-yo'qmi bilib olasan.",
    "civilian": "Maxsus kuching yo'q. Kunduzi gaplashib, mafiyani top va ovoz ber.",
}


def _init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS games(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            winner TEXT,
            players INTEGER,
            finished_at INTEGER
        )"""
    )
    con.commit()
    con.close()


_init_db()


def log_result(chat_id, winner, players_count):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO games(chat_id, winner, players, finished_at) VALUES (?,?,?,?)",
        (chat_id, winner, players_count, int(time.time())),
    )
    con.commit()
    con.close()


def role_distribution(n):
    """O'yinchilar soniga qarab rollarni taqsimlaydi."""
    mafia_count = max(1, n // 4)
    roles = ["mafia"] * mafia_count
    if n >= 4:
        roles.append("doctor")
    if n >= 5:
        roles.append("detective")
    while len(roles) < n:
        roles.append("civilian")
    random.shuffle(roles)
    return roles[:n]


class Player:
    def __init__(self, user_id, name):
        self.user_id = user_id
        self.name = name
        self.role = None
        self.alive = True


class Game:
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    FINISHED = "finished"

    MIN_PLAYERS = 4

    def __init__(self, chat_id, host_id):
        self.chat_id = chat_id
        self.host_id = host_id
        self.phase = Game.LOBBY
        self.players = {}  # user_id -> Player
        self.lobby_message_id = None
        self.night_actions = {}  # role -> {actor_id: target_id}
        self.votes = {}  # voter_id -> target_id
        self.round = 0
        self.last_night_result = None

    # ---------- lobby ----------
    def add_player(self, user_id, name):
        if user_id in self.players:
            return False
        self.players[user_id] = Player(user_id, name)
        return True

    def player_list_text(self):
        if not self.players:
            return "Hali hech kim qo'shilmadi."
        return "\n".join(f"• {p.name}" for p in self.players.values())

    def can_start(self):
        return len(self.players) >= Game.MIN_PLAYERS

    def start(self):
        roles = role_distribution(len(self.players))
        for player, role in zip(self.players.values(), roles):
            player.role = role
        self.phase = Game.NIGHT
        self.round = 1

    # ---------- helpers ----------
    def alive_players(self):
        return [p for p in self.players.values() if p.alive]

    def players_by_role(self, role):
        return [p for p in self.alive_players() if p.role == role]

    def get(self, user_id):
        return self.players.get(user_id)

    # ---------- night ----------
    def record_night_action(self, role, actor_id, target_id):
        self.night_actions.setdefault(role, {})[actor_id] = target_id

    def night_ready(self):
        """Barcha tirik maxsus rollar tanlov qildimi?"""
        for role in ("mafia", "doctor", "detective"):
            actors = self.players_by_role(role)
            if actors and len(self.night_actions.get(role, {})) < len(actors):
                return False
        return True

    def resolve_night(self):
        mafia_targets = list(self.night_actions.get("mafia", {}).values())
        killed = None
        if mafia_targets:
            # eng ko'p ovoz olgan nishon
            killed = max(set(mafia_targets), key=mafia_targets.count)

        saved_ids = set(self.night_actions.get("doctor", {}).values())
        if killed in saved_ids:
            killed = None

        if killed and killed in self.players:
            self.players[killed].alive = False

        detective_results = {}
        for actor_id, target_id in self.night_actions.get("detective", {}).items():
            target = self.players.get(target_id)
            if target:
                detective_results[actor_id] = (target.name, target.role == "mafia")

        self.night_actions = {}
        self.phase = Game.DAY
        self.last_night_result = killed
        return killed, detective_results

    # ---------- voting ----------
    def record_vote(self, voter_id, target_id):
        self.votes[voter_id] = target_id

    def votes_ready(self):
        return len(self.votes) >= len(self.alive_players())

    def resolve_vote(self):
        if not self.votes:
            self.votes = {}
            return None
        tally = list(self.votes.values())
        eliminated_id = max(set(tally), key=tally.count)
        if eliminated_id in self.players:
            self.players[eliminated_id].alive = False
        self.votes = {}
        self.round += 1
        self.phase = Game.NIGHT
        return eliminated_id

    # ---------- win check ----------
    def check_winner(self):
        alive = self.alive_players()
        mafia = [p for p in alive if p.role == "mafia"]
        others = [p for p in alive if p.role != "mafia"]
        if not mafia:
            return "civilians"
        if len(mafia) >= len(others):
            return "mafia"
        return None


class GameManager:
    def __init__(self):
        self.games = {}  # chat_id -> Game

    def get(self, chat_id):
        return self.games.get(chat_id)

    def create(self, chat_id, host_id):
        game = Game(chat_id, host_id)
        self.games[chat_id] = game
        return game

    def end(self, chat_id):
        self.games.pop(chat_id, None)
