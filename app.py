import os
import hmac
import hashlib
import json
import threading
import time
from urllib.parse import parse_qsl

from flask import Flask, request, render_template, jsonify
from flask_socketio import SocketIO, join_room, emit

import bot_api as tg
import game as G
import store as S

BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")  # https://your-app.onrender.com/app
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "changeme")
NIGHT_SECONDS = int(os.environ.get("NIGHT_SECONDS", 45))
VOTE_SECONDS = int(os.environ.get("VOTE_SECONDS", 45))

app = Flask(__name__)
# "threading" rejimi eventlet'siz ishlaydi — Render'ning yangi Python
# versiyalarida eventlet buziladigan muammolardan xoli, qo'shimcha
# kutubxona ham kerak emas.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

manager = G.GameManager()
lock = threading.Lock()
admin_state = {}  # admin_user_id -> "broadcast" | "channel"


# ---------------------------------------------------------------------------
# Telegram WebApp initData tekshiruvi (soxta so'rovlarni bloklaydi)
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
# ---------------------------------------------------------------------------
def validate_init_data(init_data: str):
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = pairs.pop("hash", None)
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if calc_hash != received_hash:
            return None
        return json.loads(pairs.get("user", "{}"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Majburiy obuna
# ---------------------------------------------------------------------------
def is_subscribed(user_id):
    channel = S.required_channel()
    if not channel:
        return True
    data = tg.get_chat_member(channel, user_id)
    if not data.get("ok"):
        return True  # bot kanalda admin emas yoki xato — foydalanuvchini bloklamaymiz
    status = data["result"].get("status")
    return status in ("creator", "administrator", "member")


def send_subscribe_prompt(chat_id):
    channel = S.required_channel()
    handle = channel if channel.startswith("@") else f"@{channel}"
    tg.send_message(
        chat_id,
        "📌 Botdan foydalanish uchun avval quyidagi kanalga obuna bo'ling, "
        "so'ng \"✅ Tekshirdim\" tugmasini bosing.",
        reply_markup=tg.kb([
            [tg.button("📢 Kanalga o'tish", url=f"https://t.me/{handle.lstrip('@')}")],
            [tg.button("✅ Tekshirdim", callback_data="check_sub")],
        ]),
    )


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------
def admin_menu_keyboard():
    return tg.kb([
        [tg.button("📊 Statistika", callback_data="admin_stats")],
        [tg.button("📢 Xabar yuborish", callback_data="admin_broadcast")],
        [tg.button("📌 Majburiy kanal", callback_data="admin_channel")],
        [tg.button("🎮 Faol o'yinlar", callback_data="admin_games")],
    ])


def handle_admin_command(chat_id):
    tg.send_message(chat_id, "🛠 <b>Admin panel</b>", reply_markup=admin_menu_keyboard())


def handle_admin_text(user_id, chat_id, text):
    """Admin broadcast yoki kanal nomini matn sifatida yuborganda ishlaydi."""
    state = admin_state.get(user_id)
    if state == "broadcast":
        admin_state.pop(user_id, None)
        ids = S.all_user_ids()
        sent, failed = 0, 0
        for uid in ids:
            res = tg.send_message(uid, text)
            if res.get("ok"):
                sent += 1
            else:
                failed += 1
            time.sleep(0.05)  # Telegram flood-limitiga tegmaslik uchun
        tg.send_message(chat_id, f"✅ Yuborildi: {sent} ta\n❌ Yetmadi: {failed} ta")
        return True
    if state == "channel":
        admin_state.pop(user_id, None)
        if text.strip().lower() in ("yo'q", "yoq", "-", "off", "bekor"):
            S.set_setting("required_channel", "")
            tg.send_message(chat_id, "Majburiy obuna o'chirildi.")
        else:
            S.set_setting("required_channel", text.strip())
            tg.send_message(chat_id, f"Majburiy kanal o'rnatildi: {text.strip()}")
        return True
    return False


def handle_admin_callback(cq_id, user_id, chat_id, data):
    if data == "admin_stats":
        tg.answer_callback(cq_id)
        tg.send_message(
            chat_id,
            f"👥 Foydalanuvchilar: {S.user_count()}\n"
            f"🎮 Faol o'yinlar: {len(manager.games)}\n"
            f"🏁 Yakunlangan o'yinlar: {S.game_count()}\n"
            f"📌 Majburiy kanal: {S.required_channel() or 'o‘rnatilmagan'}",
        )
    elif data == "admin_broadcast":
        tg.answer_callback(cq_id)
        admin_state[user_id] = "broadcast"
        tg.send_message(chat_id, "Barcha foydalanuvchilarga yuboriladigan xabarni yozing:")
    elif data == "admin_channel":
        tg.answer_callback(cq_id)
        admin_state[user_id] = "channel"
        tg.send_message(
            chat_id,
            "Kanal username'ini yuboring (masalan @mening_kanalim).\n"
            "O'chirish uchun \"yo'q\" deb yozing.",
        )
    elif data == "admin_games":
        tg.answer_callback(cq_id)
        if not manager.games:
            tg.send_message(chat_id, "Hozir faol o'yin yo'q.")
        else:
            lines = [
                f"Chat {cid}: {len(g.players)} o'yinchi, holat: {g.phase}"
                for cid, g in manager.games.items()
            ]
            tg.send_message(chat_id, "\n".join(lines))


# ---------------------------------------------------------------------------
# Klaviaturalar
# ---------------------------------------------------------------------------
def lobby_keyboard():
    rows = [[tg.button("✅ Qo'shilish", callback_data="join")]]
    if WEBAPP_URL:
        rows.append([tg.button("🎭 Rolimni Mini App'da ko'rish", web_app_url=WEBAPP_URL)])
    rows.append([tg.button("▶️ Boshlash (admin)", callback_data="begin")])
    return tg.kb(rows)


def targets_keyboard(action, alive_players, exclude_id=None):
    rows = []
    for p in alive_players:
        if p.user_id == exclude_id:
            continue
        rows.append([tg.button(p.name, callback_data=f"{action}:{p.user_id}")])
    return tg.kb(rows)


# ---------------------------------------------------------------------------
# O'yin oqimi
# ---------------------------------------------------------------------------
def start_night(gm: G.Game):
    gm.phase = G.Game.NIGHT
    gm.night_actions = {}
    tg.send_message(
        gm.chat_id,
        f"🌙 <b>{gm.round}-kecha tushdi.</b> Shahar uxlamoqda...\n"
        f"Maxsus rollar shaxsiy xabarlarida harakat qilyapti. ⏳ {NIGHT_SECONDS} soniya.",
    )
    for role in ("mafia", "doctor", "detective"):
        actors = gm.players_by_role(role)
        alive = gm.alive_players()
        for actor in actors:
            verb = {
                "mafia": "🔫 Kimni yo'q qilamiz?",
                "doctor": "💉 Kimni davolaymiz?",
                "detective": "🕵️ Kimni tekshiramiz?",
            }[role]
            tg.send_message(
                actor.user_id,
                verb,
                reply_markup=targets_keyboard(f"night_{role}", alive,
                                               exclude_id=actor.user_id if role != "doctor" else None),
            )
    threading.Timer(NIGHT_SECONDS, lambda: resolve_night_safe(gm.chat_id)).start()


def resolve_night_safe(chat_id):
    with lock:
        gm = manager.get(chat_id)
        if not gm or gm.phase != G.Game.NIGHT:
            return
        killed, detective_results = gm.resolve_night()
        for actor_id, (name, is_mafia) in detective_results.items():
            verdict = "MAFIYA! 🔴" if is_mafia else "tinch fuqaro ✅"
            tg.send_message(actor_id, f"🕵️ Tekshiruv natijasi: <b>{name}</b> — {verdict}")

        if killed:
            victim = gm.players[killed]
            tg.send_message(gm.chat_id, f"☠️ Tong otdi. <b>{victim.name}</b> o'ldirilgan holda topildi.")
        else:
            tg.send_message(gm.chat_id, "🌅 Tong otdi. Bu kecha hech kim o'lmadi.")

        winner = gm.check_winner()
        if winner:
            finish_game(gm, winner)
            return
        start_voting(gm)


def start_voting(gm: G.Game):
    gm.phase = G.Game.VOTING
    gm.votes = {}
    alive = gm.alive_players()
    names = ", ".join(p.name for p in alive)
    tg.send_message(
        gm.chat_id,
        f"🗣 Muhokama vaqti! Tirik qolganlar: {names}\n"
        f"Kimni shubha qilyapsiz? Pastdagi tugmalar orqali ovoz bering. ⏳ {VOTE_SECONDS} soniya.",
        reply_markup=targets_keyboard("vote", alive),
    )
    threading.Timer(VOTE_SECONDS, lambda: resolve_vote_safe(gm.chat_id)).start()


def resolve_vote_safe(chat_id):
    with lock:
        gm = manager.get(chat_id)
        if not gm or gm.phase != G.Game.VOTING:
            return
        eliminated_id = gm.resolve_vote()
        if eliminated_id and eliminated_id in gm.players:
            p = gm.players[eliminated_id]
            tg.send_message(
                gm.chat_id,
                f"⚖️ Guruh qarori bilan <b>{p.name}</b> chetlashtirildi. "
                f"Uning roli: {G.ROLE_NAMES[p.role]}",
            )
        else:
            tg.send_message(gm.chat_id, "⚖️ Ovozlar teng keldi, hech kim chetlashtirilmadi.")

        winner = gm.check_winner()
        if winner:
            finish_game(gm, winner)
            return
        start_night(gm)


def finish_game(gm: G.Game, winner):
    gm.phase = G.Game.FINISHED
    text = "🏆 <b>Tinch aholi g'alaba qozondi!</b>" if winner == "civilians" else "🏆 <b>Mafiya g'alaba qozondi!</b>"
    reveal = "\n".join(f"{p.name} — {G.ROLE_NAMES[p.role]}" for p in gm.players.values())
    tg.send_message(gm.chat_id, f"{text}\n\nBarcha rollar:\n{reveal}")
    G.log_result(gm.chat_id, winner, len(gm.players))
    manager.end(gm.chat_id)


# ---------------------------------------------------------------------------
# Telegram webhook
# ---------------------------------------------------------------------------
@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    try:
        if "message" in update:
            handle_message(update["message"])
        elif "callback_query" in update:
            handle_callback(update["callback_query"])
    except Exception as e:
        print("XATO webhookda:", e)
    return jsonify(ok=True)


def handle_message(msg):
    text = (msg.get("text") or "").strip()
    chat = msg["chat"]
    user = msg["from"]

    if chat["type"] == "private":
        S.touch_user(user["id"], user.get("first_name", ""), user.get("username", ""))

    # admin holati kutayotgan matn (broadcast/kanal) — boshqa hamma narsadan oldin
    if chat["type"] == "private" and S.is_admin(user["id"]) and user["id"] in admin_state \
            and not text.startswith("/"):
        if handle_admin_text(user["id"], chat["id"], text):
            return

    if text.startswith("/admin") and chat["type"] == "private":
        if S.is_admin(user["id"]):
            handle_admin_command(chat["id"])
        return

    if text.startswith("/mafia") and chat["type"] in ("group", "supergroup"):
        if not is_subscribed(user["id"]):
            send_subscribe_prompt(chat["id"])
            return
        with lock:
            if manager.get(chat["id"]):
                tg.send_message(chat["id"], "Bu guruhda allaqachon o'yin boshlangan.")
                return
            gm = manager.create(chat["id"], user["id"])
        tg.send_message(
            chat["id"],
            "🎭 <b>Mafiya lobbysi ochildi!</b>\nO'yinni boshlashdan oldin botni shaxsiy chatda ishga tushiring "
            f"(t.me/{BOT_USERNAME}), so'ng pastdagi tugma orqali qo'shiling.\n\n"
            + gm.player_list_text(),
            reply_markup=lobby_keyboard(),
        )
    elif text.startswith("/start") and chat["type"] == "private":
        if not is_subscribed(user["id"]):
            send_subscribe_prompt(chat["id"])
            return
        tg.send_message(
            chat["id"],
            "👋 Salom! Bu bot orqali guruhingizda Mafiya o'yinini o'ynashingiz mumkin.\n"
            "Guruhda <code>/mafia</code> buyrug'ini yozing va lobbyga qo'shiling.",
        )


def handle_callback(cb):
    data = cb.get("data", "")
    user = cb["from"]
    message = cb.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    cq_id = cb["id"]

    if chat_id and message.get("chat", {}).get("type") == "private":
        S.touch_user(user["id"], user.get("first_name", ""), user.get("username", ""))

    if data == "check_sub":
        if is_subscribed(user["id"]):
            tg.answer_callback(cq_id, "Rahmat! Endi botdan foydalanishingiz mumkin.")
            tg.send_message(chat_id, "✅ Obuna tasdiqlandi. Guruhda /mafia deb yozing yoki shu yerda /start bosing.")
        else:
            tg.answer_callback(cq_id, "Hali obuna bo'lmadingiz.", show_alert=True)
        return

    if data.startswith("admin_"):
        if S.is_admin(user["id"]):
            handle_admin_callback(cq_id, user["id"], chat_id, data)
        else:
            tg.answer_callback(cq_id, "Ruxsat yo'q.")
        return

    if data == "join":
        with lock:
            gm = manager.get(chat_id)
            if not gm or gm.phase != G.Game.LOBBY:
                tg.answer_callback(cq_id, "Lobby mavjud emas.")
                return
            name = user.get("first_name", "O'yinchi")
            added = gm.add_player(user["id"], name)
            if not added:
                tg.answer_callback(cq_id, "Siz allaqachon qo'shilgansiz.")
                return
            tg.edit_message(
                chat_id,
                message["message_id"],
                "🎭 <b>Mafiya lobbysi ochiq!</b>\n\n" + gm.player_list_text(),
                reply_markup=lobby_keyboard(),
            )
        tg.answer_callback(cq_id, "Qo'shildingiz!")

    elif data == "begin":
        with lock:
            gm = manager.get(chat_id)
            if not gm or gm.phase != G.Game.LOBBY:
                tg.answer_callback(cq_id, "Boshlab bo'lmaydi.")
                return
            if user["id"] != gm.host_id and not tg.is_chat_admin(chat_id, user["id"]):
                tg.answer_callback(cq_id, "Faqat admin boshlashi mumkin.", show_alert=True)
                return
            if not gm.can_start():
                tg.answer_callback(cq_id, f"Kamida {G.Game.MIN_PLAYERS} o'yinchi kerak.", show_alert=True)
                return
            gm.start()
        tg.answer_callback(cq_id, "O'yin boshlandi!")
        for p in gm.players.values():
            tg.send_message(
                p.user_id,
                f"🎴 Sizning rolingiz: <b>{G.ROLE_NAMES[p.role]}</b>\n{G.ROLE_DESC[p.role]}",
            )
        start_night(gm)

    elif data.startswith("night_"):
        role, target_id = data.split(":")[0].replace("night_", ""), int(data.split(":")[1])
        with lock:
            gm = find_game_by_actor(user["id"])
            if not gm or gm.phase != G.Game.NIGHT:
                tg.answer_callback(cq_id, "Kechasi tugadi.")
                return
            gm.record_night_action(role, user["id"], target_id)
            ready = gm.night_ready()
        tg.answer_callback(cq_id, "Tanlov qabul qilindi.")
        if ready:
            resolve_night_safe(gm.chat_id)

    elif data.startswith("vote:"):
        target_id = int(data.split(":")[1])
        with lock:
            gm = manager.get(chat_id)
            if not gm or gm.phase != G.Game.VOTING:
                tg.answer_callback(cq_id, "Ovoz berish tugadi.")
                return
            gm.record_vote(user["id"], target_id)
            ready = gm.votes_ready()
        tg.answer_callback(cq_id, "Ovozingiz qabul qilindi.")
        if ready:
            resolve_vote_safe(chat_id)


def find_game_by_actor(user_id):
    """Shaxsiy chatdan kelgan tugma bosilganda, o'sha odam qaysi o'yinda ekanini topadi."""
    for gm in manager.games.values():
        if user_id in gm.players:
            return gm
    return None


# ---------------------------------------------------------------------------
# Mini App (rol ko'rsatish sahifasi + ovozli xona)
# ---------------------------------------------------------------------------
@app.route("/app")
def miniapp():
    return render_template("index.html")


@app.route("/api/me")
def api_me():
    init_data = request.args.get("initData", "")
    user = validate_init_data(init_data)
    if not user:
        return jsonify(error="invalid_init_data"), 403
    gm = find_game_by_actor(user["id"])
    if not gm:
        return jsonify(joined=False)
    p = gm.get(user["id"])
    return jsonify(
        joined=True,
        chat_id=gm.chat_id,
        phase=gm.phase,
        alive=p.alive,
        role=p.role,
        role_name=G.ROLE_NAMES.get(p.role, "?"),
        role_desc=G.ROLE_DESC.get(p.role, ""),
    )


# ---------------------------------------------------------------------------
# WebRTC ovozli chat uchun signalling (media serversiz, brauzer-brauzer mesh).
# Har bir mijoz o'z sid'i nomli xonaga avtomatik qo'shiladi, shuning uchun
# signalni aniq bitta odamga "target" orqali yo'naltirish mumkin.
# ---------------------------------------------------------------------------
voice_rooms = {}  # room -> set(sid)


@socketio.on("join_voice")
def on_join_voice(data):
    room = str(data.get("room"))
    join_room(room)
    existing = list(voice_rooms.get(room, set()))
    voice_rooms.setdefault(room, set()).add(request.sid)
    emit("existing_peers", {"peers": existing})
    emit("peer_joined", {"sid": request.sid}, room=room, include_self=False)


@socketio.on("signal")
def on_signal(data):
    # data: {target, from, type, sdp/candidate}
    data["from"] = request.sid
    emit("signal", data, room=data.get("target"))


@socketio.on("leave_voice")
def on_leave_voice(data):
    room = str(data.get("room"))
    voice_rooms.get(room, set()).discard(request.sid)
    emit("peer_left", {"sid": request.sid}, room=room, include_self=False)


@socketio.on("disconnect")
def on_disconnect():
    for room, sids in voice_rooms.items():
        if request.sid in sids:
            sids.discard(request.sid)
            emit("peer_left", {"sid": request.sid}, room=room)


@app.route("/")
def health():
    return "Mafia bot ishlayapti."


@app.route("/set_webhook")
def do_set_webhook():
    base = request.args.get("base") or WEBAPP_URL.rsplit("/app", 1)[0]
    res = tg.set_webhook(f"{base}/webhook/{WEBHOOK_SECRET}")
    return jsonify(res)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
