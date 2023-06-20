# A wechat bot using [whochat](https://github.com/amchii/whochat)

## 环境
* Python版本>=3.8, 推荐使用最新版本
* Redis，用来缓存消息，复读计数等。


安装依赖包:
```shell
pip install -r requirements.txt
```
通过环境变量或创建`.env`文件进行配置，默认配置项：

```python
BOT_WEBSOCKET_RPC_ADDRESS = "ws://127.0.0.1:9002"  # WhoChat websocket rpc 地址
WECHAT_MESSAGE_RPC_ADDRESS = "ws://127.0.0.1:9001"  # WhoChat 消息转发websocket地址
WECHAT_REVOKE_FORWARD_TO = "filehelper"  # 撤回消息转发对象
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_PASSWORD = None
REPEATER_CHATROOM_IDS = "all"  # 复读机生效群
CHATTER_CHATROOM_IDS = "all"  # Chatgpt生效群，如 '["18426088123@chatroom", "20813231234@chatroom"]'
REVOKE_BLOCKER_WXIDS = "all"  # 防撤回转发生效群
PRIVATE_CHATTER_SENDER_IDS = "all"  # 私聊Chatgpt生效用户
LOG_LEVEL = "INFO"
ADMIN_WXIDS = []  # 管理员
```

```shell
python main.py
```
