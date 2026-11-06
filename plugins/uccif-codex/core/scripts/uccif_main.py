"""Interpreter entry point used by bin/uccif.

Puts the plugin root on sys.path itself, so the launcher passes only a file
path (which Git Bash converts for native Windows Python) and never sets
PYTHONPATH (whose ':' separator and /c/... paths Windows Python misreads).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Hooks talk JSON over stdin/stdout in UTF-8. On Windows Python defaults to the
# locale code page, which cannot print the token line's emoji or read a
# Vietnamese prompt. Python 3.7+ can switch the streams in place.
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from uccif_lib.cli import main  # noqa: E402

sys.exit(main())
