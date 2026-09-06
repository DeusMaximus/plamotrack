"""Credential-free access and authentication diagnostics (T10).

The record factory runs before any handler can format or copy credentials. The
app installs it before constructing the authentication libraries. Logging handler
configuration does not replace the record factory. Requests and OAuth
protocol decisions are untouched; nginx owns its separate request log format.
"""

import logging


class PrivateLogRecords:
    def __init__(self, previous):
        self.previous = previous

    def __call__(self, *args, **kwargs) -> logging.LogRecord:
        record = self.previous(*args, **kwargs)
        if record.name == "uvicorn.access":
            # Both shipped HTTP parsers emit peer, method, path+query, version,
            # status. Real-server tests pin this upstream record contract.
            if isinstance(record.args, tuple) and len(record.args) == 5:
                peer, method, target, version, status = record.args
                if isinstance(target, str):
                    record.args = (peer, method, target.partition("?")[0], version, status)
        elif record.name.startswith(("fastmcp.server.auth.", "mcp.server.auth.")):
            # Library diagnostics include state/transaction IDs, provider error
            # descriptions and exceptions, sometimes already interpolated into
            # the message. Keep severity/source, never their opaque payloads.
            # Our own auth logger and audit events retain safe event details.
            record.msg = "Authentication library diagnostic; sensitive details omitted."
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return record


def install_log_hygiene() -> None:
    previous = logging.getLogRecordFactory()
    if not isinstance(previous, PrivateLogRecords):
        logging.setLogRecordFactory(PrivateLogRecords(previous))
