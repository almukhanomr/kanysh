"""Kanysh Basic: one domain service behind every interface."""

import os

__version__ = "0.2.0.dev6"

# Local tool for confidential field data: third-party libraries must not phone home.
# Gradio reads these at import time (analytics, version check, Hugging Face telemetry).
for _name, _value in (
    ("GRADIO_ANALYTICS_ENABLED", "False"),
    ("HF_HUB_DISABLE_TELEMETRY", "1"),
    ("HF_HUB_OFFLINE", "1"),
):
    os.environ.setdefault(_name, _value)
