"""Bounded Windows read-sharing recovery for editor project publication only."""
import os
import time
from story_director import atomic_json

def publish(path,data):
    for attempt in range(8):
        try:return atomic_json(path,data)
        except PermissionError as error:
            if os.name!='nt' or getattr(error,'winerror',None) not in (5,32,33) or attempt==7:raise
            time.sleep(.01*2**min(attempt,4))
