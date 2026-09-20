"""Entry point for `python -m yolk`.

The console script above generates a small launcher executable in the
virtual environment's Scripts directory. Windows Smart App Control blocks
those, because a launcher stamped out locally has no reputation, while the
interpreter it wraps does. Running the module skips the launcher entirely,
so this is the invocation the documentation uses.
"""

from yolk.cli import main

raise SystemExit(main())
