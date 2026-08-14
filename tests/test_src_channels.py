import channels

class TestCommChannel(channels.CommChannel):

    started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        raise NotImplementedError()

    def receive(self) -> str:
        raise NotImplementedError()

    def send(self, message: str) -> None:
        raise NotImplementedError()


class AttachmentCommChannel(TestCommChannel):
    def __init__(self):
        self.sent_attachments = []

    def send_attachment(self, attachment_id: str, message: str) -> bool:
        self.sent_attachments.append((attachment_id, message))
        return True


def test_commchannel_config():
    channel = TestCommChannel()
    channels.registerCommChannel("Test", channel)
    channels.commChannelStart("Test")
    assert channel.started


def test_default_channel_does_not_claim_attachment_support():
    channel = TestCommChannel()
    channels.registerCommChannel("without-attachments", channel)
    channels.commChannelStart("without-attachments")

    assert channels.commChannelSendAttachment("attachment-id", "message") is False


def test_attachment_send_delegates_only_to_selected_channel():
    selected = AttachmentCommChannel()
    unselected = AttachmentCommChannel()
    channels.registerCommChannel("selected", selected)
    channels.registerCommChannel("unselected", unselected)
    channels.commChannelStart("selected")

    assert channels.commChannelSendAttachment("attachment-id", "message") is True
    assert selected.sent_attachments == [("attachment-id", "message")]
    assert unselected.sent_attachments == []
