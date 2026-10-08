"""Main entry point for running evaluator as a module: python -m experiment.evaluator."""

import sys
from .evaluator import main

if __name__ == "__main__":
    sys.exit(main())
