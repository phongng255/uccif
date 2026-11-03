import sys

# Hooks talk JSON over stdin/stdout in UTF-8. On Windows Python defaults to the
# locale code page, which cannot print the token line's emoji or read a
# Vietnamese prompt. Python 3.7+ can switch the streams in place.
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from uccif_lib.cli import main

sys.exit(main())
