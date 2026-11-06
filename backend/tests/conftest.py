"""Loaded by pytest before any test module: point the app at a throwaway database FIRST.

Without this, a test module that imports the app before test_core.py would bind the engine to the
developer database from .env, and the test fixtures would drop and reseed it.
"""
import os
import tempfile

os.environ['DATABASE_URL'] = 'sqlite:///' + tempfile.mktemp(suffix='.db')
