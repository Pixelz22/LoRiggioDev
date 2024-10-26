# LoRiggio bot by Pixelz22


import logging
import json
import discord
from discord import app_commands
import os.path

from utils import srcpath, whisper, shout
import LiarsDice

logging.getLogger("discord").setLevel(logging.INFO)  # Silence Discord.py debug
logging.basicConfig(level=logging.DEBUG)

log = logging.getLogger("loriggio")

# Loading/creating bot config

if os.path.exists(srcpath("config.json")):
    print("config exists")

configuration = json.load(open('config.json'))

TOKEN = configuration["token"]


# Setting up client
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)  # Build command tree

loriggio = app_commands.Group(name="loriggio", description="testing?")

# region Bot Events

@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')

@client.event
async def on_message(msg: discord.Message):
    f_log = log.getChild("event.on_message")
    # Message synchronization command
    if msg.content.startswith("loriggio/sync") and msg.author.id == configuration["owner_id"]:  # Perform sync
        split = msg.content.split()
        if len(split) == 1:
            await tree.sync()
        else:
            if split[1] == "this":
                g = msg.guild
            else:
                g = discord.Object(id=int(split[1]))
            tree.copy_global_to(guild=g)
            await tree.sync(guild=g)
        f_log.info("Performed authorized sync.")
        await msg.add_reaction("✅")  # leave confirmation
        return
    if msg.content.startswith("loriggio/clear") and msg.author.id == configuration["owner_id"]:  # Perform sync
        split = msg.content.split()
        if len(split) == 1:
            tree.clear_commands(guild=None)
        else:
            if split[1] == "this":
                g = msg.guild
            else:
                g = discord.Object(id=int(split[1]))
            tree.clear_commands(guild=g)
        f_log.info("Cleared command tree.")
        await msg.add_reaction("✅")  # leave confirmation
        return

# endregion

@loriggio.command()
async def psst(ctx: discord.Interaction):
    await whisper(ctx, "psssssssst")

@loriggio.command()
async def ping(ctx: discord.Interaction, user: discord.User):
    await shout(ctx, f"Hello, {user.mention}! Your ID is {user.id}")


# Register the slash commands
tree.add_command(loriggio)
tree.add_command(LiarsDice.ld_group)
# Start the bot
client.run(TOKEN)
