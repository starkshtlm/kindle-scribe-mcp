"""What the bridge knows about itself at runtime.

A leaf module on purpose: app.py and mailbox.py both use it, neither imports
the other, and the trust boundary stays in one place. The object is passed into
the poll loop the same way store_document is, rather than shared as module
state.

This exists because dropping the \\Seen flag removed the last visible sign that
polling works. Without it, a mailbox that has never authenticated looks exactly
like a mailbox with nothing new in it -- to the user, and to the model.
"""

import time


class MailboxStatus:
    def __init__(self) -> None:
        self.connected_at: float | None = None
        self.last_poll_ok_at: float | None = None
        self.last_error: str = ""
        self.last_error_at: float | None = None
        self.consecutive_failures: int = 0
        self.documents_imported: int = 0
        self.folder: str = ""
        self.uidvalidity: int | None = None
        self.last_settled_uid: int | None = None

    def poll_succeeded(self, folder: str, uidvalidity: int | None,
                       last_uid: int | None) -> None:
        now = time.time()
        if self.connected_at is None:
            self.connected_at = now
        self.last_poll_ok_at = now
        self.consecutive_failures = 0
        self.last_error = ""
        self.folder = folder
        self.uidvalidity = uidvalidity
        self.last_settled_uid = last_uid

    def poll_failed(self, error: Exception) -> None:
        # Truncated: a server's error text can carry the address or the command
        # that failed, and this is served over an endpoint.
        self.last_error = f"{type(error).__name__}: {error}"[:200]
        self.last_error_at = time.time()
        self.consecutive_failures += 1

    def document_imported(self) -> None:
        self.documents_imported += 1

    @property
    def ever_connected(self) -> bool:
        return self.connected_at is not None

    def as_dict(self) -> dict:
        """Safe to serve: names what is configured and what happened, never a
        credential. Anything added here must stay free of secrets."""
        return {
            "ever_connected": self.ever_connected,
            "last_poll_ok_at": self.last_poll_ok_at,
            "seconds_since_last_poll": (
                round(time.time() - self.last_poll_ok_at)
                if self.last_poll_ok_at else None
            ),
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "documents_imported": self.documents_imported,
            "checkpoint": {
                "folder": self.folder,
                "uidvalidity": self.uidvalidity,
                "last_settled_uid": self.last_settled_uid,
            },
        }
