"""Launch the formal desktop UI without starting or stopping backend services."""
import sys
from main import main

if __name__ == '__main__':
    sys.argv.append('--frontend')
    raise SystemExit(main())
