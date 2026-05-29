import os
import sys

from channels import irc, mattermost, mock, slack, telegram, wschat


_config_registry = {}


class AbstractChannel:
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        raise NotImplementedError

    def receive(self) -> str:
        raise NotImplementedError

    def send(self, message: str) -> None:
        raise NotImplementedError


def _get_config(name: str, default: str = "", aliases=()) -> str:
    names = (name, *aliases)

    for key in names:
        value = _config_registry.get(key)
        if value not in (None, ""):
            return value

    for key in names:
        value = os.environ.get(key)
        if value not in (None, ""):
            return value

    for key in names:
        prefix = f"{key}="
        for arg in sys.argv[1:]:
            if arg.startswith(prefix):
                return arg[len(prefix):]

    return default


def _get_int_config(name: str, default: int, aliases=()) -> int:
    value = _get_config(name, str(default), aliases=aliases)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class IrcChannel(AbstractChannel):
    def __init__(self):
        super().__init__("irc")

    def start(self) -> None:
        irc.start_irc(
            channel=_get_config("IRC_channel", "##omegaclaw", aliases=("IRC_CHANNEL",)),
            server=_get_config("IRC_server", "irc.quakenet.org", aliases=("IRC_SERVER",)),
            port=_get_int_config("IRC_port", 6667, aliases=("IRC_PORT",)),
            nick=_get_config("IRC_user", "omegaclaw", aliases=("IRC_USER",)),
        )

    def receive(self) -> str:
        return irc.getLastMessage()

    def send(self, message: str) -> None:
        irc.send_message(message)


class TelegramChannel(AbstractChannel):
    def __init__(self):
        super().__init__("telegram")

    def start(self) -> None:
        telegram.start_telegram(
            bot_token=_get_config("TG_BOT_TOKEN", ""),
            chat_id=_get_config("TG_CHAT_ID", ""),
            poll_timeout=_get_int_config("TG_POLL_TIMEOUT", 20),
        )

    def receive(self) -> str:
        return telegram.getLastMessage()

    def send(self, message: str) -> None:
        telegram.send_message(message)


class SlackChannel(AbstractChannel):
    def __init__(self):
        super().__init__("slack")

    def start(self) -> None:
        slack.start_slack(
            bot_token=_get_config("SL_BOT_TOKEN", ""),
            channel_id=_get_config("SL_CHANNEL_ID", ""),
            poll_interval=_get_int_config("SL_POLL_INTERVAL", 60),
        )

    def receive(self) -> str:
        return slack.getLastMessage()

    def send(self, message: str) -> None:
        slack.send_message(message)


class MattermostChannel(AbstractChannel):
    def __init__(self):
        super().__init__("mattermost")

    def start(self) -> None:
        mattermost.start_mattermost(
            _get_config("MM_URL", "https://chat.singularitynet.io"),
            _get_config("MM_CHANNEL_ID", "8fjrmabjx7gupy7e5kjznpt5qh"),
            _get_config("MM_BOT_TOKEN", ""),
        )

    def receive(self) -> str:
        return mattermost.getLastMessage()

    def send(self, message: str) -> None:
        mattermost.send_message(message)


class WebsocketChannel(AbstractChannel):
    def __init__(self):
        super().__init__("websocket")

    def start(self) -> None:
        wschat.start_websocket(
            ws_url=_get_config("WS_URL", ""),
            ws_token=_get_config("WS_TOKEN", ""),
        )

    def receive(self) -> str:
        return wschat.getLastMessage()

    def send(self, message: str) -> None:
        wschat.send_message(message)


class MockChannel(AbstractChannel):
    def __init__(self):
        super().__init__("mock")

    def start(self) -> None:
        server_ip = _get_config("TEST_SERVER_IP", "")
        if server_ip:
            os.environ["TEST_SERVER_IP"] = server_ip
        mock.start_mock()

    def receive(self) -> str:
        return mock.getLastMessage()

    def send(self, message: str) -> None:
        mock.send_message(message)


_channel_registry = {}


def _register_channel(channel: AbstractChannel) -> None:
    _channel_registry[channel.name] = channel


def setConfig(name, value) -> None:
    """Store runtime configuration values resolved by MeTTa."""
    _config_registry[str(name)] = str(value)


_register_channel(IrcChannel())
_register_channel(TelegramChannel())
_register_channel(SlackChannel())
_register_channel(MattermostChannel())
_register_channel(WebsocketChannel())
_register_channel(MockChannel())
_channel_registry["test"] = _channel_registry["mock"]


def _resolve(name: str) -> AbstractChannel:
    channel = _channel_registry.get(name)
    if channel is None:
        raise RuntimeError(f"Unknown communication channel '{name}'")
    return channel


def startChannel(name: str) -> None:
    """Generic channel start dispatcher for MeTTa."""
    _resolve(name).start()


def receive(name: str) -> str:
    """Generic channel receive dispatcher for MeTTa."""
    return _resolve(name).receive()


def send(name: str, message: str) -> None:
    """Generic channel send dispatcher for MeTTa."""
    _resolve(name).send(message)
