import asyncio
import os
import subprocess
import traceback
import webbrowser
from multiprocessing import Process
from time import sleep

import openai
from dotenv import load_dotenv

from src.utils.database.client import get_database

from src.world.base import World

from .utils.colors import LogColor
from .utils.database.base import Tables
from .utils.formatting import print_to_console
from .utils.logging import init_logging
from .web import get_server
from .utils.general import get_open_port

load_dotenv()

init_logging()





def run_server():
    app = get_server()
    port = get_open_port()
    run_in_new_loop(app.run_task(port=port))


def run_in_new_loop(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    finally:
        loop.close()


def run():
    port = get_open_port()

    # process_world = Process(target=run_world)
    process_server = Process(target=run_server)

    # process_world.start()
    process_server.start()

    sleep(3)

    print(f"Opening browser on port {port}...")
    webbrowser.open(f"http://127.0.0.1:{port}")

    # process_world.join()
    process_server.join()


def main():
    run()
