import asyncio
import contextvars
import dataclasses
import functools
import json
import logging
import os
import pickle
from typing import Dict, TypedDict

import requests
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict

from wechatbot.os_signals import Signal

default_headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
}

default_chat_url = ""

cached_session_file = "cache/session.pickle"

default_timeout = 60 * 5

cached_chatgpt_pickle_file = "cache/chatgpt.pickle"

logger = logging.getLogger("wechatbot")


def get_cookie_jar() -> RequestsCookieJar:
    cookie_jar = RequestsCookieJar()
    with open("cache/cookies.json", "r", encoding="utf-8") as fp:
        cookie_list = json.load(fp)

    for cookie in cookie_list:
        name = cookie.pop("name")
        value = cookie.pop("value")
        cookie_jar.set(name, value, **cookie)
    return cookie_jar


def save_session(s: requests.Session, file=cached_session_file):
    with open(file, "wb") as fp:
        pickle.dump(s, fp)


def get_session() -> requests.Session:
    if not os.path.exists(cached_session_file):
        session = requests.Session()
        session.headers = CaseInsensitiveDict(default_headers)
        session.cookies = get_cookie_jar()
        save_session(session)
        return session

    with open(cached_session_file, "rb") as fp:
        session = pickle.load(fp)
        return session


class auto:  # noqa
    pass


@dataclasses.dataclass
class Chatroom:
    id: str
    current_message_id: int = None
    current_message: str = None
    initial_prompt: str = None


class CaredResult(TypedDict):
    text: str


class ChatGPT:
    def __init__(
        self,
        chat_url: str = default_chat_url,
        session: requests.Session = None,
        timeout: int = default_timeout,
        *,
        pickle_file: str = None,
    ):
        self.chat_url = chat_url
        self.session = session or get_session()
        self.timeout = timeout
        self.pickle_file = pickle_file
        self.chatrooms: Dict[int, "Chatroom"] = {}
        if pickle_file and os.path.exists(pickle_file):
            other = ChatGPT.load(pickle_file)
            self.clone(other)
        Signal.register_shutdown(self.close)

    def post(self, json_=None, stream=True, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        logger.debug(f"ChatGPT POST: {json_}, kwargs: {kwargs}")
        return self.session.post(self.chat_url, json=json_, stream=stream, **kwargs)

    def _chat(self, chatroom_id, prompt: str, parent_message_id: str):
        """实现你自己的聊天方法"""
        raise NotImplementedError

    def update_chatroom(self, chatroom_id, result):
        chatroom = self.chatrooms[chatroom_id]
        chatroom.current_message_id = result["id"]
        chatroom.current_message = result["text"]

    def reset_chatroom(self, chatroom_id):
        chatroom = Chatroom(id=chatroom_id)
        self.chatrooms[chatroom_id] = chatroom

    def new_chat(self, chatroom_id, prompt: str):
        return self.chat(chatroom_id, prompt, parent_message_id=None)

    def chat(
        self, chatroom_id, prompt: str, parent_message_id: str | None = auto
    ) -> CaredResult:
        if chatroom_id not in self.chatrooms:
            chatroom = Chatroom(id=chatroom_id)
            self.chatrooms[chatroom_id] = chatroom
        else:
            chatroom = self.chatrooms[chatroom_id]
        if parent_message_id is auto:
            parent_message_id = chatroom.current_message_id

        if not parent_message_id:
            chatroom.initial_prompt = prompt
        return self._chat(chatroom_id, prompt, parent_message_id)

    async def async_chat(
        self, chatroom_id, prompt: str, parent_message_id: str | None = auto
    ) -> CaredResult:
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        func_call = functools.partial(
            ctx.run, self.chat, chatroom_id, prompt, parent_message_id
        )
        return await loop.run_in_executor(None, func_call)

    def save_session(self, file):
        logger.info(f"Saving {self.session} to {file}...")
        save_session(self.session, file)
        logger.info(f"{self.session} saved to {file}")

    def save(self, pickle_file=None):
        pickle_file = pickle_file or self.pickle_file or cached_chatgpt_pickle_file
        logger.info(f"Saving {self} to {pickle_file}...")
        with open(pickle_file, "wb") as fp:
            pickle.dump(self, fp)
        logger.info(f"Saved {self} to {pickle_file}")

    @classmethod
    def load(cls, pickle_file=None) -> "ChatGPT":
        pickle_file = pickle_file or cached_chatgpt_pickle_file
        try:
            with open(pickle_file, "rb") as fp:
                return pickle.load(fp)
        except OSError:
            return cls()

    def close(self):
        self.save()
        self.save_session(cached_session_file)
        return True

    def clone(self, chatgpt: "ChatGPT"):
        self.session = chatgpt.session
        self.chatrooms = chatgpt.chatrooms


class ChatGPTFactory:
    _instances = {}

    @classmethod
    def get(cls, pickle_file=None) -> "ChatGPT":
        pickle_file = pickle_file or cached_chatgpt_pickle_file
        if pickle_file not in cls._instances:
            cls._instances[pickle_file] = ChatGPT(pickle_file=pickle_file)
        return cls._instances[pickle_file]
