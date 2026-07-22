import os


# Gateway tests import the application during collection and must use its test profile.
os.environ.setdefault("NODE_ENV", "test")
