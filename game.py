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
    "mayor": "🎖 Mer",
    "maniac": "🔪 Yakka Qotil",
    "civilian": "👤 Tinch aholi",
}

ROLE_DESC = {
    "mafia": "Har kecha bitta odamni yo'q qilasan. Kunduzi o'zingni tinch aholidek tut.",
    "doctor": "Har kecha bitta odamni (o'zingni ham) o'limdan qutqarasan.",
    "detective": "Har kecha bitta odamni tekshirib, u mafiyami-yo'qmi bilib olasan.",
    "mayor": "Tinch aholi tomonidasan. Kunduzi ovoz berganingda ovozing 2 kishilik hisoblanadi.",
    "maniac": "Hech kim tomonida emassan — o'zing uchun o'ynaysan. Har kecha birini yo'q qilasan. "
              "Faqat SEN tirik qolsang — yutasan.",
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
    if n >= 6:
        roles.append("mayor")
    if n >= 7:
        roles.append("maniac")
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
        return "\n".join(f"{i}. {p.name}" for i, p in enumerate(self.players.values(), 1))

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
        for role in ("mafia", "doctor", "detective", "maniac"):
            actors = self.players_by_role(role)
            if actors and len(self.night_actions.get(role, {})) < len(actors):
                return False
        return True

    def resolve_night(self):
        saved_ids = set(self.night_actions.get("doctor", {}).values())

        def top_target(role):
            targets = list(self.night_actions.get(role, {}).values())
            if not targets:
                return None
            return max(set(targets), key=targets.count)

        killed_ids = set()
        mafia_target = top_target("mafia")
        if mafia_target and mafia_target not in saved_ids:
            killed_ids.add(mafia_target)
        maniac_target = top_target("maniac")
        if maniac_target and maniac_target not in saved_ids:
            killed_ids.add(maniac_target)

        killed_players = []
        for pid in killed_ids:
            if pid in self.players and self.players[pid].alive:
                self.players[pid].alive = False
                killed_players.append(self.players[pid])

        detective_results = {}
        for actor_id, target_id in self.night_actions.get("detective", {}).items():
            target = self.players.get(target_id)
            if target:
                detective_results[actor_id] = (target.name, target.role == "mafia")

        self.night_actions = {}
        self.phase = Game.DAY
        return killed_players, detective_results

    # ---------- voting ----------
    def record_vote(self, voter_id, target_id):
        self.votes[voter_id] = target_id

    def votes_ready(self):
        return len(self.votes) >= len(self.alive_players())

    def resolve_vote(self):
        if not self.votes:
            self.votes = {}
            return None
        tally = []
        for voter_id, target_id in self.votes.items():
            voter = self.players.get(voter_id)
            weight = 2 if voter and voter.role == "mayor" else 1
            tally.extend([target_id] * weight)
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
        maniac = [p for p in alive if p.role == "maniac"]

        if maniac and len(alive) == 1:
            return "maniac"

        mafia = [p for p in alive if p.role == "mafia"]
        others = [p for p in alive if p.role != "mafia"]
        if not mafia:
            return None if maniac else "civilians"
        if len(mafia) >= len(others):
            return None if maniac else "mafia"
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
