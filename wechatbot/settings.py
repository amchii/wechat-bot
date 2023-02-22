import pathlib

from pydantic import BaseSettings


class Settings(BaseSettings):
    DEBUG: bool = False
    ROOT_DIR: str | pathlib.Path = pathlib.Path(__file__).parent.parent.absolute()
    LOG_DIR: str | pathlib.Path = ROOT_DIR.joinpath("logs")
    BOT_WEBSOCKET_RPC_ADDRESS: str = "ws://127.0.0.1:9002"
    WECHAT_MESSAGE_RPC_ADDRESS: str = "ws://127.0.0.1:9001"
    WECHAT_REVOKE_FORWARD_TO: str = "filehelper"
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = None
    REPEATER_CHATROOM_IDS: list[str] | str = "all"
    CHATTER_CHATROOM_IDS: list[str] | str = "all"
    REVOKE_BLOCKER_WXIDS: list[str] | str = "all"
    PRIVATE_CHATTER_SENDER_IDS: list[str] | str = "all"
    LOG_LEVEL: str = "INFO"
    ADMIN_WXIDS: list[str] | str = []

    class Config:
        env_file = ".env"


settings = Settings()
