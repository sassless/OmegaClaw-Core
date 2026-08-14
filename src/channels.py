import logging

logger = logging.getLogger(__name__)

_commChannelRegistry = {}

class CommChannel:
    """Communication channel implementation"""

    def start(self) -> None:
        """Configure and start communication channel"""
        raise NotImplementedError()

    def stop(self) -> None:
        """Stop communication channel and free resources"""
        raise NotImplementedError()

    def receive(self) -> str:
        """Receive message from the communication channel"""
        raise NotImplementedError()

    def send(self, message: str) -> None:
        """Send message via the communication channel"""
        raise NotImplementedError()

    def send_attachment(self, attachment_id: str, message: str) -> bool:
        """Send one existing attachment when supported by the channel."""
        return False

def registerCommChannel(id: str, channel: CommChannel) -> None:
    """Register communication channel in the registry"""
    global _commChannelRegistry
    logger.info(f"registerCommChannel: registering communication channel {id}")
    _commChannelRegistry[id] = channel

_commchannel: CommChannel = None

def commChannelStart(commchannel):
    """Select and start one of the communication channels registered by
    plugins"""
    global _commchannel
    _commchannel = _commChannelRegistry.get(commchannel, None)
    if _commchannel is None:
        _error("commChannelStart", f"Communication channel plugin {commchannel} is not registered")
    _commchannel.start()

def commChannelReceive():
    """Receive message from selected communication channel"""
    global _commchannel
    return _commchannel.receive()

def commChannelSend(message):
    """Send message via selected communication channel"""
    global _commchannel
    _commchannel.send(message)

def commChannelSendAttachment(attachment_id, message):
    """Send an existing attachment through the selected channel."""
    global _commchannel
    return _commchannel.send_attachment(attachment_id, message)
