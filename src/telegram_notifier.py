"""Telegram notifier stub — not required for OpenClaw routing.

OpenClaw handles channel routing; this module exists only to satisfy imports.
All notification output is produced as structured JSON on stdout by the main script.
"""


def load_telegram_config():
    return None


def send_telegram_notification(config, event_data):
    pass


def send_telegram_digest(config, events):
    pass
