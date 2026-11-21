"""Les tests datent leurs exemples en heure de Paris, fuseau du service (compose.yaml)."""
import os
import time

os.environ["TZ"] = "Europe/Paris"
time.tzset()
