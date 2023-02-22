import asyncio
import logging
from functools import partial

from whochat.messages.websocket import WechatMessageWebsocketClient
from whochat.rpc.clients.websocket import (
    BotWebsocketRPCClient,
    OneBotWebsocketRPCClient,
)

from wechatbot.bot import global_context, on_message
from wechatbot.settings import settings

logger = logging.getLogger("wechatbot")


async def main():
    bot_rpc_client = BotWebsocketRPCClient(settings.BOT_WEBSOCKET_RPC_ADDRESS)
    bot_rpc_client.consume_in_background()
    results = await bot_rpc_client.list_wechat()
    pid = int(results[0]["pid"])
    o = OneBotWebsocketRPCClient(pid, bot_rpc_client)
    self_info = await o.get_self_info()
    logger.info(self_info)
    image_hook_path = await o.hook_image_msg("Images")
    voice_hook_path = await o.hook_voice_msg("Voices")
    wechat_base_path = await o.get_base_directory()
    global_context["self_info"] = self_info
    global_context["wxid"] = self_info["wxId"]
    global_context["image_hook_path"] = image_hook_path
    global_context["voice_hook_path"] = voice_hook_path
    global_context["wechat_base_path"] = wechat_base_path
    message_client = WechatMessageWebsocketClient(settings.WECHAT_MESSAGE_RPC_ADDRESS)

    await message_client.start_consumer(partial(on_message, o=o))


if __name__ == "__main__":
    asyncio.run(main())
