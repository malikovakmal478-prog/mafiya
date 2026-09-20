"""
Telegram Bot API bilan to'g'ridan-to'g'ri ishlaydigan yengil qatlam.
Katta kutubxonalar (aiogram/PTB) o'rniga oddiy requests ishlatilgan —
Render'ning bepul tarifida barqaror ishlaydi, xotira kam yeydi.
"""
import os
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _call(method, **params):
    try:
        r = requests.post(f"{API_URL}/{method}", json=params, timeout=10)
        data = r.json()
        if not data.get("ok"):
            print(f"[TG API XATO] {method}: {data}")
        return data
    except Exception as e:
        print(f"[TG API ISTISNO] {method}: {e}")
        return {"ok": False}


def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    return _call(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    return _call(
        "editMessageText",
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


def answer_callback(callback_query_id, text=None, show_alert=False):
    return _call(
        "answerCallbackQuery",
        callback_query_id=callback_query_id,
        text=text,
        show_alert=show_alert,
    )


def get_chat_member(chat_id, user_id):
    return _call("getChatMember", chat_id=chat_id, user_id=user_id)


def is_chat_admin(chat_id, user_id):
    data = get_chat_member(chat_id, user_id)
    if not data.get("ok"):
        return False
    status = data["result"].get("status")
    return status in ("creator", "administrator")


def set_webhook(url):
    return _call("setWebhook", url=url)


def button(text, callback_data=None, web_app_url=None, url=None):
    b = {"text": text}
    if callback_data:
        b["callback_data"] = callback_data
    if web_app_url:
        b["web_app"] = {"url": web_app_url}
    if url:
        b["url"] = url
    return b


def kb(rows):
    """rows: list of list of button() dicts"""
    return {"inline_keyboard": rows}
