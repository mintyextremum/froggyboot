"""Telegram notifications and approve/deny buttons. Uses only the standard library."""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse
import urllib.request
from typing import Callable

log = logging.getLogger("froggyboot.telegram")


class Notifier:
    def __init__(self, token: str = "", chat: str = "",
                 on_decision: Callable[[int, bool, str], str | None] | None = None):
        self.token, self.chat, self.on_decision = token, str(chat), on_decision
        self._stop = threading.Event()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat)

    def _call(self, method: str, http_timeout: float = 10, **params) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = urllib.parse.urlencode(
            {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in params.items()}).encode()
        with urllib.request.urlopen(url, data=data, timeout=http_timeout) as r:
            return json.load(r)

    def send(self, text: str, approval_id: int | None = None) -> None:
        """Fire and forget: a dead Telegram must never slow down a boot."""
        if not self.enabled:
            return
        params: dict = {"chat_id": self.chat, "text": text}
        if approval_id is not None:
            params["reply_markup"] = {"inline_keyboard": [[
                {"text": "Approve", "callback_data": f"ap:{approval_id}:1"},
                {"text": "Deny", "callback_data": f"ap:{approval_id}:0"},
            ]]}
        threading.Thread(target=self._safe_call, args=("sendMessage",), kwargs=params, daemon=True).start()

    def _safe_call(self, method: str, **params) -> None:
        try:
            self._call(method, **params)
        except Exception as e:  # network errors are logged, never raised
            log.warning("telegram %s failed: %s", method, e)

    def start_polling(self) -> None:
        if self.enabled and self.on_decision:
            threading.Thread(target=self._poll, daemon=True, name="telegram-poll").start()

    def stop(self) -> None:
        self._stop.set()

    def _poll(self) -> None:
        offset = 0
        while not self._stop.is_set():
            try:
                res = self._call("getUpdates", http_timeout=40, offset=offset, timeout=30,
                                 allowed_updates=["callback_query"])
            except Exception as e:
                log.debug("getUpdates: %s", e)
                self._stop.wait(10)
                continue
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                self.handle_update(upd)

    def handle_update(self, upd: dict) -> None:
        cq = upd.get("callback_query")
        if not cq:
            return
        msg = cq.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != self.chat:
            return  # buttons pressed in any other chat are ignored
        parts = str(cq.get("data", "")).split(":")
        if len(parts) != 3 or parts[0] != "ap" or not parts[1].isdigit():
            return
        who = "telegram:" + str((cq.get("from") or {}).get("username") or (cq.get("from") or {}).get("id"))
        result = self.on_decision(int(parts[1]), parts[2] == "1", who) if self.on_decision else None
        self._safe_call("answerCallbackQuery", callback_query_id=cq["id"], text=result or "Already decided")
        if result and msg.get("message_id"):
            self._safe_call("editMessageText", chat_id=self.chat, message_id=msg["message_id"],
                            text=f"{msg.get('text', '')}\n\n{result} by {who}")
