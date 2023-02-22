import asyncio
import hashlib
import json
import logging
import os.path
import random
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

import requests.exceptions
from redis import asyncio as aredis
from whochat.messages.constants import WechatMsgType
from whochat.rpc.clients.websocket import OneBotWebsocketRPCClient

from wechatbot.chatgpt import ChatGPTFactory
from wechatbot.settings import settings

redis_client = aredis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=settings.REDIS_PASSWORD,
    db=2,
)

wechat_revoke_time = 121
wechat_message_store_ex = 1200

global_context = {}

logger = logging.getLogger("wechatbot")


def get_revoked_msgid(message):
    m = re.search(r"<newmsgid>(.*?)</newmsgid>", message["message"])
    if m:
        return int(m.group(1))


class SenderID:
    ALL = "all"


class MessageConsumer:
    async def consume(self, o: OneBotWebsocketRPCClient, message: dict):
        raise NotImplementedError

    async def consume_robust(self, o: OneBotWebsocketRPCClient, message: dict):
        try:
            await self.consume(o, message)
        except Exception as e:
            logger.exception(e)

    @classmethod
    def from_room(cls, message) -> bool:
        return message["sender"].endswith("@chatroom")

    @classmethod
    def from_target_room(cls, message, target_room_id):
        if cls.from_room(message):
            chatroom_id = message["sender"]
            return chatroom_id == target_room_id or target_room_id == SenderID.ALL
        return False

    @classmethod
    def from_target_rooms(cls, message, target_room_ids):
        if cls.from_room(message):
            chatroom_id = message["sender"]
            return chatroom_id in target_room_ids or target_room_ids == SenderID.ALL
        return False

    @classmethod
    def from_target_users(cls, message, target_wxids):
        if message["isSendMsg"]:
            return False
        if cls.is_private(message):
            sender = message["sender"]
            return sender in target_wxids or target_wxids == SenderID.ALL
        return False

    @classmethod
    def is_at_me(cls, message):
        return (
            message["extrainfo"]["is_at_msg"] is True
            and global_context["wxid"] in message["extrainfo"]["at_user_list"]
        )

    @classmethod
    def only_at_me(cls, message):
        return cls.is_at_me(message) and len(message["extrainfo"]["at_user_list"]) == 1

    @classmethod
    def is_private(cls, message):
        return not cls.from_room(message)

    @classmethod
    def from_admin(cls, wxid: str):
        return wxid in settings.ADMIN_WXIDS

    async def send_at_text(
        self,
        o,
        chatroom_id: str,
        at_wxids: List[str],
        text: str,
        auto_nickname: bool = True,
    ):
        return await o.send_at_text(chatroom_id, at_wxids, text, auto_nickname)

    async def send_text(self, o, wxid, text):
        return await o.send_text(wxid, text)


class WxID:
    ALL = "all"


class RevokeBlocker(MessageConsumer):
    def __init__(
        self,
        wxids: list[str] = WxID.ALL,
        forward_to: str = None,
    ):
        super().__init__()
        self.wxids = wxids
        self.forward_to = forward_to

    async def forward(self, o, message, revoked_msg):
        if not self.forward_to:
            return
        wxid = message["wxid"]
        forward_message = (
            f"用户「{wxid}」撤回消息，类型「{WechatMsgType(int(revoked_msg['type'])).name}」"
        )
        await self.send_text(o, self.forward_to, forward_message)
        logger.info("撤回内容:")
        logger.info(f"消息类型: {WechatMsgType(int(revoked_msg['type'])).name}")
        content = ""
        if revoked_msg["type"] == WechatMsgType.文字:
            content = revoked_msg["message"]
            await self.send_text(o, self.forward_to, content)
        elif revoked_msg["type"] == WechatMsgType.图片:
            message = re.search(r".*?\\(\w+?)\.dat", revoked_msg["filepath"])
            if message:
                content = global_context["wxid"] + "\\" + message.group(1) + ".jpg"
                await o.send_image(self.forward_to, f"{content}")

        elif revoked_msg["type"] == WechatMsgType.语音:
            content = str(revoked_msg["sign"]) + ".amr"
        elif revoked_msg["type"] == WechatMsgType.视频:
            video_path = os.path.splitext(revoked_msg["thumb_path"])[0] + ".mp4"
            content = video_path
            await o.send_image(
                self.forward_to,
                global_context["wechat_base_path"] + "\\" + content,
            )

        logger.info(f"消息内容: {content}")

    async def consume(self, o: OneBotWebsocketRPCClient, message: dict):
        sender = message["sender"]
        if self.wxids != WxID.ALL and sender not in self.wxids:
            return

        now = datetime.now()
        if message["type"] in (
            WechatMsgType.图片,
            WechatMsgType.语音,
            WechatMsgType.视频,
        ):
            if message["type"] == WechatMsgType.视频:
                thumb_path = message["thumb_path"]
                video_path = os.path.splitext(thumb_path)[0] + ".mp4"
                await o.prevent_revoke(thumb_path)
                await o.prevent_revoke(video_path)
        if (
            message["type"] == WechatMsgType.撤回_群语音邀请
            and "<revokemsg>" in message["message"]
        ):
            revoked_msgid = get_revoked_msgid(message)
            logger.info(
                f"发现撤回消息, 撤回消息msgid: {revoked_msgid}, 用户微信ID: {message['wxid']}"
            )
            revoked_msg_str = await redis_client.get(str(revoked_msgid))
            if not revoked_msg_str:
                return
            await redis_client.hset(
                f"revoke:{now.date()}:{message['wxid']}",
                str(revoked_msgid),
                revoked_msg_str,
            )
            try:
                revoked_msg = json.loads(revoked_msg_str)
                await self.forward(o, message, revoked_msg)

            except json.JSONDecodeError:
                logger.info(f"撤回内容为：{revoked_msg_str}")


class Repeater(MessageConsumer):
    def __init__(
        self,
        repeat_when=3,
        repeat_timeout=120,
        chatroom_ids: SenderID | list[str] = SenderID.ALL,
        *args,
        **kwargs,
    ):
        super().__init__()
        self.repeat_when = repeat_when
        self.repeat_timeout = repeat_timeout
        self.chatroom_ids = chatroom_ids

    async def do_repeat(self, o, chatroom_id, repeat_message: str):
        await self.send_text(o, chatroom_id, repeat_message)

    async def consume(self, o: OneBotWebsocketRPCClient, message: dict):
        if not message["type"] == WechatMsgType.文字:
            return
        if not self.from_target_rooms(message, self.chatroom_ids):
            return
        chatroom_id = message["sender"]
        hash_ = hashlib.md5(message["message"].encode("utf-8")).hexdigest()
        message_count_key = f"{chatroom_id}:message:{hash_}:count"
        try:
            message_count = int(await redis_client.get(message_count_key))
            message_count += 1
            message_count_key_ttl = max(await redis_client.ttl(message_count_key), 1)
            await redis_client.set(
                message_count_key,
                message_count,
                ex=message_count_key_ttl,
            )
        except (TypeError, ValueError):
            message_count = 1
            await redis_client.set(
                message_count_key, message_count, ex=self.repeat_timeout
            )
        repeated_key = f"{chatroom_id}:message:repeated:{hash_}"

        if message_count >= self.repeat_when:
            if not await redis_client.exists(repeated_key):
                await self.do_repeat(o, chatroom_id, message["message"])
                await redis_client.set(repeated_key, 1, ex=self.repeat_timeout)


class Responder(MessageConsumer):
    def __init__(
        self,
        chatroom_ids=SenderID.ALL,
        echo_words: list[str] = None,
    ):
        super().__init__()
        self.chatroom_ids = chatroom_ids
        self.echo_words = echo_words

    async def do_echo(
        self,
        o,
        message: dict,
    ):
        if not self.echo_words:
            return
        wxid = message["wxid"]
        await self.send_at_text(
            o, message["sender"], [wxid], random.choice(self.echo_words)
        )

    async def consume(self, o: OneBotWebsocketRPCClient, message: dict):
        if not self.from_target_rooms(message, self.chatroom_ids):
            return
        if message["message"] == "echo":
            await self.do_echo(o, message)


class Chatter(MessageConsumer):
    def __init__(
        self,
        sender_ids: SenderID | list[str] = SenderID.ALL,
    ):
        super().__init__()
        self.sender_ids = sender_ids
        self.chatgpt = ChatGPTFactory.get(pickle_file="cache/chatter.chatgpt.pickle")
        self.sender_id_thinking: Dict[str, bool] = defaultdict(bool)

    def still_thinking(self, chatroom_id):
        return self.sender_id_thinking[chatroom_id]

    def get_pure_text(self, message):
        m = re.match(r"^@.*?(\u2005|\s)(.*)", message["message"])
        if not m:
            logger.warning(f"@消息无法解析，完整消息内容: {message}")
            return
        pure_text = m.group(2).strip()
        return pure_text

    async def _chat(self, o, message):
        chatroom_id = message["sender"]
        wxid = message["wxid"]
        start = time.perf_counter()
        pure_text = self.get_pure_text(message)

        if not pure_text:
            return await self.send_at_text(o, chatroom_id, [wxid], "说点什么❓")
        if pure_text == "/reset":
            if self.from_admin(wxid):
                self.chatgpt.reset_chatroom(chatroom_id)
                return await self.send_at_text(o, chatroom_id, [wxid], "已重置😳")
            else:
                return await self.send_at_text(o, chatroom_id, [wxid], "不熟🙅")
        max_text_length = 300
        if len(pure_text) > 300:
            return await self.send_at_text(
                o, chatroom_id, [wxid], f"你话太多了，一次最多接受不超过{max_text_length}个字符🗣"
            )

        try:
            result = await self.chatgpt.async_chat(chatroom_id, pure_text)
        except requests.exceptions.ConnectionError:
            return await self.send_at_text(o, chatroom_id, [wxid], "我的网络出了点问题，请稍后试试😦")
        text = result["text"]
        texts = []
        for index in range(0, len(text), max_text_length):
            _text = text[index : index + max_text_length]
            texts.append(_text)
        texts[-1] += f"\n...\n本次回复耗时: {int(time.perf_counter() - start)}秒👀"
        for i, _text in enumerate(texts):
            if i == 0:
                await self.send_at_text(o, chatroom_id, [wxid], _text)
            else:
                await self.send_text(o, chatroom_id, _text)
            await asyncio.sleep(0.1)

    async def chat(self, o, message):
        chatroom_id = message["sender"]
        wxid = message["wxid"]
        if self.still_thinking(chatroom_id):
            return await self.send_at_text(o, chatroom_id, [wxid], "上一条还没完成呢🙏")
        self.sender_id_thinking[chatroom_id] = True
        try:
            await self._chat(o, message)
        finally:
            self.sender_id_thinking[chatroom_id] = False

    async def consume(self, o: OneBotWebsocketRPCClient, message: dict):
        if not self.from_target_rooms(message, self.sender_ids):
            return

        if self.only_at_me(message):
            await self.chat(o, message)


class PrivateChatter(Chatter):
    """私聊中的Chatter"""

    def get_pure_text(self, message):
        return message["message"]

    async def send_at_text(
        self,
        o,
        chatroom_id: str,
        at_wxids: List[str],
        text: str,
        auto_nickname: bool = True,
    ):
        return await self.send_text(o, chatroom_id, text)

    async def chat(self, o, message):
        if message["type"] != WechatMsgType.文字:
            return
        if self.get_pure_text(message) == "echo":
            return await self.send_text(o, message["sender"], "在呢")
        return await super().chat(o, message)

    async def consume(self, o: OneBotWebsocketRPCClient, message: dict):
        if not self.from_target_users(message, self.sender_ids):
            return
        await self.chat(o, message)


revoke_blocker = RevokeBlocker(
    settings.REVOKE_BLOCKER_WXIDS, settings.WECHAT_REVOKE_FORWARD_TO
)
responder = Responder(echo_words=["嗯？", "是吗？", "然后呢？", "？？"])
repeater = Repeater(chatroom_ids=settings.REPEATER_CHATROOM_IDS)
chatter = Chatter(sender_ids=settings.CHATTER_CHATROOM_IDS)
private_chatter = PrivateChatter(sender_ids=settings.PRIVATE_CHATTER_SENDER_IDS)


async def _on_message(raw_message: str | bytes, o: OneBotWebsocketRPCClient):
    logger.debug(f"收到消息:\n {raw_message}")
    message = json.loads(raw_message)
    if message["type"] < 50:
        await redis_client.set(
            message["msgid"], raw_message, ex=wechat_message_store_ex
        )
    await asyncio.gather(
        revoke_blocker.consume_robust(o, message),
        responder.consume_robust(o, message),
        repeater.consume_robust(o, message),
        chatter.consume_robust(o, message),
        private_chatter.consume_robust(o, message),
    )


async def on_message(raw_message: str | bytes, o: OneBotWebsocketRPCClient):
    asyncio.create_task(_on_message(raw_message, o))
