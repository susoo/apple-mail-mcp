"""Entry point for `python -m apple_mail_mcp` and `apple-mail-mcp` CLI."""

import argparse
import os
import threading
import time

import apple_mail_mcp.server as server
from apple_mail_mcp import paths


# Workaround for modelcontextprotocol/python-sdk#526.
# When the MCP client (e.g. Claude) exits without closing stdin cleanly,
# the FastMCP server can keep running orphaned in the background. The
# orphaned server keeps polling Mail.app via Apple Events, which causes
# Mail to relaunch after the user quits it. Capture the initial PPID at
# startup and self-terminate when it changes (parent died, we have been
# reparented). Uses os._exit because sys.exit does not tear down FastMCP's
# background asyncio loop reliably. get_ppid and exit_fn are injectable
# for unit testing.
def _start_orphan_watcher(
    interval_sec: int = 10,
    get_ppid=os.getppid,
    exit_fn=os._exit,
) -> None:
    initial_ppid = get_ppid()

    def _watch() -> None:
        while True:
            if get_ppid() != initial_ppid:
                exit_fn(0)
                return
            time.sleep(interval_sec)

    threading.Thread(target=_watch, daemon=True).start()


def _remove_tool(mcp, name: str) -> None:
    """Unregister a tool by name, ignoring names that were never registered.

    Goes through the server's local provider rather than FastMCP.remove_tool:
    the latter is deprecated in fastmcp 3.x and gone in 4.x, while
    local_provider.remove_tool exists (and raises KeyError on a miss) in both.
    """
    try:
        mcp.local_provider.remove_tool(name)
    except KeyError:
        pass


MUTATING_TOOLS = [
    "compose_email",
    "reply_to_email",
    "forward_email",
    "create_rich_email_draft",
    "manage_drafts",
    "move_email",
    "update_email_status",
    "manage_trash",
    "create_mailbox",
]


def main():
    _start_orphan_watcher()

    parser = argparse.ArgumentParser(description="Apple Mail MCP Server")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Remove every tool that sends, drafts, moves, flags, deletes or "
             "creates anything in Mail. Local file writes (save_email_attachment, "
             "export_emails) remain, restricted by --write-dir.",
    )
    parser.add_argument(
        "--write-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Only allow file-writing tools to write inside DIR (repeatable). "
             "Adds to APPLE_MAIL_MCP_WRITE_DIRS. Default: anywhere except "
             "protected locations.",
    )
    parser.add_argument(
        "--attach-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Only allow attaching files from inside DIR (repeatable). "
             "Adds to APPLE_MAIL_MCP_ATTACH_DIRS. Default: any file except secrets.",
    )
    args = parser.parse_args()

    server.READ_ONLY = args.read_only
    paths.configure(write_dirs=args.write_dir, attach_dirs=args.attach_dir)

    from apple_mail_mcp import mcp  # noqa: E402

    if args.read_only:
        for name in MUTATING_TOOLS:
            _remove_tool(mcp, name)

    mcp.run()


if __name__ == "__main__":
    main()
