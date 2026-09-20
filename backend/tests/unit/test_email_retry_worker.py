"""Tests for the `retry_failed_emails` worker.

This task had no coverage at all, which is how a crash on every single run
reached production: DynamoDB returns numbers as `decimal.Decimal`, and a
Decimal cannot index `THROTTLE_BACKOFF_SECONDS`. From 2026-08-21 20:51 until
it was fixed, every five-minute run raised "tuple indices must be integers",
abandoned the whole batch, and still reported `status: "completed"`.

The tests therefore drive the task through a real (moto) table so the values
it reads are Decimals, exactly as in production.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.services.email_client import EmailResult
from app.workers.handler import THROTTLE_BACKOFF_SECONDS, retry_failed_emails

NOW = datetime.now(timezone.utc)

THROTTLE_ERROR = (
    "SMTP error: {'sofia@example.com': (450, b'4.7.0 Transmit rate limit "
    "exceeded, try again later (ACC)')}"
)


def _msg(**overrides) -> dict:
    event_id = uuid4()
    message_id = uuid4()
    defaults = {
        "pk": f"EVENT#{event_id}",
        "sk": f"MSG#{message_id}",
        "id": str(message_id),
        "event_id": str(event_id),
        "entity_type": "Message",
        "type": "cancellation",
        "direction": "outbound",
        "subject": "Dein Platz an Bord",
        "body": "Moin!",
        "status": "failed",
        "recipient_email": "sofia@example.com",
        "retry_count": 0,
        "created_at": (NOW - timedelta(minutes=90)).isoformat(),
        "last_attempt_at": (NOW - timedelta(minutes=90)).isoformat(),
    }
    defaults.update(overrides)
    return defaults


class TestRetryFailedEmails:
    @pytest.fixture(autouse=True)
    def setup_env(self, mock_dynamodb):
        self.messages_table = mock_dynamodb["messages_table"]
        with patch(
            "app.services.config.get_messages_table",
            return_value=self.messages_table,
        ):
            yield

    def _seed(self, **overrides) -> dict:
        item = _msg(**overrides)
        self.messages_table.put_item(Item=item)
        return item

    async def _run(self):
        """Run the task with a Gmail client that always succeeds."""
        sent: list[str] = []

        class _Client:
            async def send_email(self, email):
                sent.append(email.to)
                return EmailResult(success=True, message_id=f"<{uuid4()}@example.com>")

        with patch("app.services.email_client.get_gmail_client", return_value=_Client()):
            result = await retry_failed_emails()
        return result, sent

    async def test_a_throttled_message_past_its_backoff_is_retried(self):
        """The regression: Decimal throttle_count must not kill the run."""
        self._seed(error_code=THROTTLE_ERROR, throttle_count=1)

        result, sent = await self._run()

        # Before the fix this came back completed/0 with the TypeError swallowed.
        assert result["status"] == "completed"
        assert result["retried"] == 1
        assert result["succeeded"] == 1
        assert sent == ["sofia@example.com"]

    async def test_the_retried_message_is_marked_sent(self):
        item = self._seed(error_code=THROTTLE_ERROR, throttle_count=2)

        await self._run()

        row = self.messages_table.get_item(
            Key={"pk": item["pk"], "sk": item["sk"]},
        )["Item"]
        assert row["status"] == "sent"

    async def test_a_throttled_message_still_inside_its_backoff_is_left_alone(self):
        """throttle_count=1 means a 45-minute wait; 10 minutes is too soon."""
        assert THROTTLE_BACKOFF_SECONDS[1] == 45 * 60
        self._seed(
            error_code=THROTTLE_ERROR,
            throttle_count=1,
            last_attempt_at=(NOW - timedelta(minutes=10)).isoformat(),
        )

        result, sent = await self._run()

        assert result["retried"] == 0
        assert sent == []

    async def test_a_throttle_count_beyond_the_backoff_table_clamps(self):
        """Indexing must not run off the end of the tuple."""
        self._seed(
            error_code=THROTTLE_ERROR,
            throttle_count=99,
            last_attempt_at=(NOW - timedelta(hours=4)).isoformat(),
        )

        result, _ = await self._run()

        assert result["status"] == "completed"
        assert result["retried"] == 1

    async def test_a_message_throttled_for_over_a_day_is_abandoned(self):
        self._seed(
            error_code=THROTTLE_ERROR,
            throttle_count=1,
            created_at=(NOW - timedelta(days=2)).isoformat(),
            last_attempt_at=(NOW - timedelta(days=2)).isoformat(),
        )

        result, sent = await self._run()

        assert result["retried"] == 0
        assert sent == []

    async def test_a_hard_failure_over_max_retries_is_not_retried(self):
        self._seed(error_code="521 Domain does not exist", retry_count=3)

        result, sent = await self._run()

        assert result["retried"] == 0
        assert sent == []

    async def test_an_anonymized_row_is_never_put_back_on_the_wire(self):
        """Spec 022 neutralises unsent mail with retry_count=99 and no address."""
        self._seed(error_code="anonymized", retry_count=99, recipient_email=None)

        result, sent = await self._run()

        assert result["retried"] == 0
        assert sent == []

    async def test_one_unreadable_row_does_not_abandon_the_rest(self):
        """A single bad row used to take the whole batch down with it.

        Scan order is not guaranteed, so the healthy row may be reached before
        or after the broken one — it must go out either way. That is the whole
        point: the bad row is skipped and counted, not fatal.
        """
        self._seed(error_code=THROTTLE_ERROR, throttle_count=1)
        self._seed(
            error_code=THROTTLE_ERROR,
            throttle_count=1,
            last_attempt_at="not-a-timestamp",
        )

        result, sent = await self._run()

        assert sent == ["sofia@example.com"], "the healthy row still goes out"
        assert result["succeeded"] == 1
        assert result["failed"] == 1, "the unreadable row is counted, not silently dropped"
        assert result["status"] == "completed", "skipping a row is not a task failure"

    async def test_a_task_level_crash_does_not_report_success(self):
        """The outer handler swallows exceptions; it must not call that done.

        This is the property that hid ~1000 broken runs for four days — the
        task reported status "completed", retried 0, while dying on every
        single invocation.
        """
        with patch(
            "app.services.config.get_messages_table",
            side_effect=RuntimeError("table is gone"),
        ):
            result = await retry_failed_emails()

        assert result["status"] == "failed"
