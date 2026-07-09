"""DDD Tachograph Reader — minimal CLI (delegates to tacho_cli)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.cli import main

if __name__ == "__main__":
    main()
