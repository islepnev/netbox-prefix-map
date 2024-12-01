import sys
from pathlib import Path

# Add the app directory to the module search path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import cli

if __name__ == "__main__":
    cli()
