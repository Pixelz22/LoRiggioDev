import os
import discord

from discord.utils import MISSING
from typing import Optional

__SRC__ = os.path.dirname(os.path.realpath(__file__))

def srcpath(path: str) -> str:
    return os.path.join(__SRC__, path)

async def shout(ctx: discord.Interaction, msg: Optional[str] = None, embed: discord.Embed = MISSING,
                view: discord.ui.View = MISSING, delete_after: Optional[float] = None):
    try:
        await ctx.response.send_message(content=msg, embed=embed, view=view, ephemeral=False, delete_after=delete_after)
    except discord.InteractionResponded:
        await ctx.followup.send(content=msg, embed=embed, view=view, ephemeral=False)

async def whisper(ctx: discord.Interaction, msg: Optional[str] = None, embed: discord.Embed = MISSING,
                  view: discord.ui.View = MISSING,  delete_after: Optional[float] = 15):
    try:
        await ctx.response.send_message(content=msg, embed=embed, view=view, ephemeral=True, delete_after=delete_after)
    except discord.InteractionResponded:
        await ctx.followup.send(content=msg, embed=embed, view=view, ephemeral=True)

