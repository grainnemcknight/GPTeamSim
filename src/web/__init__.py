import asyncio
import json
import os
import re
import traceback
from multiprocessing import Process

import openai
from dotenv import load_dotenv
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from quart import Quart, abort, send_file, websocket, request, jsonify

from src.utils.database.client import get_database
from src.world.base import World
from utils.models import ChatModel
from ..utils.model_name import ChatModelName
from ..utils.parameters import DEFAULT_FAST_MODEL, DEFAULT_SMART_MODEL

from ..utils.colors import LogColor
from ..utils.database.base import Tables
from ..utils.formatting import print_to_console

load_dotenv()

window_request_queue = asyncio.Queue()
window_response_queue = asyncio.Queue()

global process_world

import tiktoken


# Write function to take string input and return number of tokens
def num_tokens_from_string(string: str, encoding_name: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def run_in_new_loop(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    finally:
        loop.close()


async def run_world_async():
    openai.api_key = os.getenv("OPENAI_API_KEY")
    try:
        database = await get_database()

        worlds = await database.get_all(Tables.Worlds)

        if len(worlds) == 0:
            raise ValueError("No worlds found!")

        world = await World.from_id(worlds[-1]["id"])

        print_to_console(
            f"Welcome to {world.name}!",
            LogColor.ANNOUNCEMENT,
            "\n",
        )

        await world.run()
    except Exception:
        print(traceback.format_exc())
    finally:
        await (await get_database()).close()


def run_world():
    run_in_new_loop(run_world_async())


import subprocess


def run_db_reset_command():
    try:
        # Run the command and wait for it to complete
        subprocess.run("poetry run db-reset", shell=True, check=True)
        print("Command 'poetry run db-reset' has completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Command 'poetry run db-reset' failed with return code {e.returncode}.")
    except Exception as e:
        print(f"An error occurred: {e}")


def get_server():
    app = Quart(__name__)

    app.config["ENV"] = "development"
    app.config["DEBUG"] = True

    @app.route("/", )
    async def index():
        file_path = os.path.join(os.path.dirname(__file__), "templates/logs.html")
        return await send_file(file_path)

    @app.route("/run", )
    async def run():
        try:
            run_db_reset_command()
            global process_world
            process_world = Process(target=run_world)
            process_world.start()
            # Return a success response
            return jsonify({'message': 'World Started'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route("/stop", )
    async def stop():
        try:
            global process_world
            process_world.terminate()
            # Return a success response
            return jsonify({'message': 'World Stopped'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route("/chat", methods=["POST"])
    async def chat():
        try:
            data = await request.get_json()
            messages = []
            for message in data:
                if message.get("type") == "AI":
                    messages.append(AIMessage(content=message.get("content")))
                elif message.get("type") == "HUMAN":
                    messages.append(HumanMessage(content=message.get("content")))
                elif message.get("type") == "SYSTEM":
                    messages.append(SystemMessage(content=message.get("content")))
                else:
                    raise ValueError("Invalid message type")

            chat_llm = ChatModel(temperature=0, request_timeout=600)
            response = await chat_llm.get_chat_completion(
                messages=messages,
                loading_text="🤔 Thinking...",
            )
            # Return a success response
            return jsonify({"type": "AI",
                            "content": response}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.route("/personality", methods=["POST"])
    async def create_profile():
        # Parse the incoming JSON request data
        try:
            data = await request.get_json()
            name = data.get('first_name')
            positive_bio = data.get('private_bio')
            private_bio = data.get('public_bio')
            directives = data.get('directives')
            initial_plan = data.get('initial_plan')
            initial_plan["location"] = 'Google Head Quarters'

            if not name or not positive_bio or not private_bio:
                return jsonify({'error': 'Missing required fields'}), 400

            # Construct the new agent data
            new_agent = {
                "first_name": name,
                "private_bio": positive_bio,  # Again, check if this is correct
                "public_bio": private_bio,  # Again, check if this is correct
                "directives": directives,
                "initial_plan": initial_plan
            }

            # Load the existing data from config.json
            with open('config.json', 'r') as file:
                config_data = json.load(file)

            # Append the new agent data to the "agents" list
            config_data["agents"].append(new_agent)

            # Write the updated data back to config.json
            with open('config.json', 'w') as file:
                json.dump(config_data, file, indent=4)

            # Return a success response
            return jsonify({'message': 'Profile created successfully'}), 201

        except Exception as e:
            return jsonify({'error': str(e)}), 400

    @app.websocket("/logs")
    async def logs_websocket():
        file_path = os.path.join(os.path.dirname(__file__), "logs/agent.txt")
        position = 0
        while True:
            await asyncio.sleep(0.25)
            with open(file_path, "r") as log_file:
                log_file.seek(position)
                line = log_file.readline()
                if line:
                    position = log_file.tell()
                    matches = re.match(r"\[(.*?)\] \[(.*?)\] \[(.*?)\] (.*)$", line)
                    if matches:
                        agentName = matches.group(1).strip()
                        color = matches.group(2).strip().split(".")[1]
                        title = matches.group(3).strip()
                        description = matches.group(4).strip()

                        data = {
                            "agentName": agentName,
                            "color": color,
                            "title": title,
                            "description": description,
                        }
                        await websocket.send_json(data)

    @app.route("/analyze")
    async def logs_analyze():
        try:
            print("analyze")
            file_path = os.path.join(os.path.dirname(__file__), "logs/agent.txt")
            conversation = "Focus Group Conversation:\n"
            messages = []
            with (open(file_path, "r") as log_file):
                for line in log_file:
                    if ("Error:" not in line and
                            'plan' not in line.lower() and
                            'waiting' not in line.lower() and
                            'wait' not in line.lower() and
                            len(line) > 100):
                        conversation += line + "\n"

            count_tokens = num_tokens_from_string(conversation, "gpt-3.5-turbo")
            if count_tokens > 3048:
                conversation = conversation[:1200]
            conversation += ("\n Please list the positive and negative opinions and questions the "
                             "focus group had about the product in a maximum of 200 words.")

            messages.append(SystemMessage(content="You are a Market Researcher whose task is to "
                                                  "analyze the focus group conversation "
                                                  "transcript and identify the perceived "
                                                  "positives and negatives"
                                                  "and major questions about the product."))
            messages.append(HumanMessage(content=conversation))
            print("asking now")
            chat_llm = ChatModel(temperature=0, request_timeout=600)
            response = await chat_llm.get_chat_completion(
                messages=messages,
                loading_text="🤔 Analyzing...",
            )
            print("response")


            return jsonify(response), 201

        except Exception as e:
            print("EEEEEEEEEEEEEEEEEEERRRRRRRRRRRRROOOOOOOOOOOOOOORRRRRRRRRRR")
            print(e)
            return jsonify(str(e)), 400

    @app.websocket("/world")
    async def world_websocket():
        while True:
            await asyncio.sleep(0.25)
            database = await get_database()
            worlds = await database.get_all(Tables.Worlds)

            if not worlds:
                abort(404, "No worlds found")

            id = worlds[0]["id"]

            # get all locations
            locations = await database.get_by_field(
                Tables.Locations, "world_id", str(id)
            )

            # get all agents
            agents = await database.get_by_field(Tables.Agents, "world_id", str(id))

            location_mapping = {
                location["id"]: location["name"] for location in locations
            }

            agents_state = [
                {
                    "full_name": agent["full_name"],
                    "location": location_mapping.get(
                        agent["location_id"], "Unknown Location"
                    ),
                }
                for agent in agents
            ]

            sorted_agents = sorted(agents_state, key=lambda k: k["full_name"])

            await websocket.send_json(
                {"agents": sorted_agents, "name": worlds[0]["name"]}
            )

    @app.websocket("/window")
    async def window_websocket():
        if (
                DEFAULT_SMART_MODEL != ChatModelName.WINDOW
                and DEFAULT_FAST_MODEL != ChatModelName.WINDOW
        ):
            return

        while True:
            await asyncio.sleep(0.25)

            request = await window_request_queue.get()
            await websocket.send(request)

            response = await websocket.receive()
            await window_response_queue.put(response)

    @app.websocket("/windowmodel")
    async def window_model_websocket():
        if (
                DEFAULT_SMART_MODEL != ChatModelName.WINDOW
                and DEFAULT_FAST_MODEL != ChatModelName.WINDOW
        ):
            return

        while True:
            await asyncio.sleep(0.25)

            request = await websocket.receive()
            await window_request_queue.put(request)

            response = await window_response_queue.get()
            await websocket.send(response)

    return app
