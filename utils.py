import os

__SRC__ = os.path.dirname(os.path.realpath(__file__))

def srcpath(path: str) -> str:
    return os.path.join(__SRC__, path)
