"""Hermetic defaults for the whole pytest session.

``AppSettings`` reads the repository ``.env`` and ``app.fast_api_app`` builds an app at
import time, so without this a developer's ``.env`` (for example
``BREW_PERSISTENCE_BACKEND=firestore`` plus a real ``GOOGLE_CLOUD_PROJECT``) silently
decides which backends the tests construct. Real environment variables outrank ``.env``
for both pydantic-settings and ``load_dotenv``, so pinning them here, before any test
module is imported, keeps every test on in-memory backends unless it passes explicit
``AppSettings(...)`` arguments (which outrank the environment). The Firestore emulator
tests do exactly that. The values mirror what the CI unit job pins in
``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import os

os.environ["BREW_PERSISTENCE_BACKEND"] = "in_memory"
os.environ["BREW_SESSION_BACKEND"] = "in_memory"
os.environ["OTEL_TO_CLOUD"] = "false"
os.environ.pop("SESSION_SERVICE_URI", None)
