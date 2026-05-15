import sys
import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Name of your main bot script
SCRIPT_TO_RUN = "main.py" 

class RestartHandler(FileSystemEventHandler):
    def __init__(self, command):
        self.command = command

    def on_modified(self, event):
        if event.src_path.endswith(".py"):
            print(f"Detected change in {event.src_path}, restarting...")
            os.execv(sys.executable, ['python'] + [self.command])

if __name__ == "__main__":
    print(f"Starting {SCRIPT_TO_RUN}")

    # Start the initial process
    pid = os.fork()
    if pid == 0:
        os.execv(sys.executable, ['python'] + [SCRIPT_TO_RUN])
    else:
        # Watch for changes
        event_handler = RestartHandler(SCRIPT_TO_RUN)
        observer = Observer()
        observer.schedule(event_handler, path='.', recursive=False)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
