"""Rebuild the saved response, preserving source precision (no network)."""
import sys
from market_data import main

if __name__ == '__main__':
    main(['--input', sys.argv[1]] if len(sys.argv) > 1 else [])
