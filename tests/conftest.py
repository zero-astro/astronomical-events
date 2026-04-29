"""Pytest configuration for astronomical-events tests."""

import os
import sys

# Ensure src is on path for all tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
