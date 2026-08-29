from datetime import UTC, datetime

from agropecuario.models import EmailMessage, ProjectStatus


def test_email_message_minimal():
    m = EmailMessage(
        message_id="abc",
        thread_id="thr",
        sender="remit@example.com",
        subject="Proyecto",
        received_at=datetime.now(UTC),
    )
    assert m.message_id == "abc"
    assert m.attachments == []


def test_status_enum():
    assert ProjectStatus.APPROVED.value == "approved"
