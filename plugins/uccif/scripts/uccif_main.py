"""Interpreter entry point used by bin/uccif.

Puts the plugin root on sys.path itself, so the launcher passes only a file
path (which Git Bash converts for native Windows Python) and never sets
PYTHONPATH (whose ':' separator and /c/... paths Windows Python misreads).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uccif_lib.cli import main  # noqa: E402

sys.exit(main())
