import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from rich.console import Console

console = Console()

class VoxelHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.obj'):
            self.callback(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.obj'):
            self.callback(event.src_path)

class VoxelWatcher:
    def __init__(self, watch_path, callback):
        self.watch_path = watch_path
        self.callback = callback
        self.observer = Observer()

    def start(self):
        handler = VoxelHandler(self.callback)
        self.observer.schedule(handler, self.watch_path, recursive=False)
        self.observer.start()
        console.log(f"[bold cyan]WATCHER:[/bold cyan] Scanning {self.watch_path}...")

    def stop(self):
        self.observer.stop()
        self.observer.join()