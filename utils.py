import os
import discord

__SRC__ = os.path.dirname(os.path.realpath(__file__))

def srcpath(path: str) -> str:
    return os.path.join(__SRC__, path)

async def shout(ctx: discord.Interaction, msg: str, delete_after=None):
    try:
        await ctx.response.send_message(msg, ephemeral=False, delete_after=delete_after)
    except discord.InteractionResponded:
        await ctx.followup.send(msg, ephemeral=False)

async def whisper(ctx: discord.Interaction, msg: str, delete_after=10):
    try:
        await ctx.response.send_message(msg, ephemeral=True, delete_after=delete_after)
    except discord.InteractionResponded:
        await ctx.followup.send(msg, ephemeral=True)

