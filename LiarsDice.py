import random
import discord
from discord import app_commands
import typing

from utils import whisper, shout

class ErrorResponse(RuntimeError):
    def __init__(self, msg):
        super().__init__(msg)


class LiarsDiceGame:
    # Game Info
    creator: int                          # Discord ID of the creator
    dice_per_player: int                  # duh
    dice_sides: int                       # What type of dice we playin' with? D6? D20?
    kick_losers: bool                     # Do players get kicked from the game when they lose?
    allow_count_reset_on_increment: bool  # Can a player lower the dice count if they raise the dice num?
    players: list[int]                    # Set of Discord IDs of players in the game

    # Round Info
    in_round: bool                # are we in the middle of a round?
    round_num: int                # current round number
    raiser_idx: int               # idx of the next player to raise the bet
    current_bet: tuple[int, int]  # The current bet. Format: [dice count, # on the dice], e.g. [2, 3] = Two 3s
    cups: dict[int, list[int]]    # The cups belonging to each player. cups[player_id][X] = # of Xs that player has

    def __init__(self, creator: int, dice_per_player=5, dice_sides=6,
                 kick_losers=True, allow_count_reset_on_increment=False):
        self.creator = creator
        self.dice_per_player = dice_per_player
        self.dice_sides = dice_sides
        self.kick_losers = kick_losers
        self.allow_count_reset_on_increment = allow_count_reset_on_increment

        self.players = []
        self.cups = dict()
        self.round_num = 0  # We count rounds starting at 1. Fight me.
        self.in_round = False
        self.join(creator)

    def join(self, player_id: int):
        if self.round_num > 0:
            raise ErrorResponse("Game has started, cannot add additional players.")
        if player_id in self.players:
            raise ErrorResponse("You are already part of the game.")
        self.players.append(player_id)

    def leave(self, player_id: int):
        pass

    def begin_next_round(self):
        if self.in_round:
            raise ErrorResponse("Already in a round.")

        self.round_num += 1
        self.raiser_idx = self.round_num - 1

        for player in self.players:
            self.cups[player] = [0 for _ in range(self.dice_sides)]
            for die in [random.randint(1, self.dice_sides) for _ in range(self.dice_per_player)]:
                self.cups[player][die] += 1

        self.current_bet = 0, 0
        self.in_round = True

    def raise_bet(self, player_id: int, dice_count: int, dice_num: int):
        if player_id != self.players[self.raiser_idx]:  # wrap around on caller_idx is handled here
            raise ErrorResponse(f"It's not your turn to raise.")

        # Validate: Bet is physically possible
        if dice_num < 1 or dice_num > self.dice_sides:
            raise ErrorResponse(f"Number on the dice should be between 1 and {self.dice_sides}, inclusive.")
        if dice_count < 1:
            raise ErrorResponse("Dice count must be positive.")

        # Validate: Bet cannot be lowered (mostly)
        if dice_num < self.current_bet[1]:
            raise ErrorResponse("Cannot lower the dice number.")
        if dice_count < self.current_bet[0]:
            if self.allow_count_reset_on_increment:
                # Dice count can be lowered if dice number increases
                if dice_num <= self.current_bet[1]:
                    raise ErrorResponse("Cannot lower the dice count without raising the dice number.")
            else:
                raise ErrorResponse("Cannot lower the dice count.")

        # Validate: Part of the bet has to be raised
        if dice_count == self.current_bet[0] and dice_num == self.current_bet[1]:
            raise ErrorResponse("Bet must be raised.")

        self.current_bet = dice_count, dice_num
        self.raiser_idx += 1

    def call_bet(self, player_id: int) -> bool:
        """
        Returns whether bet was true.
        Remember that the bet is if there are AT LEAST X of Y dice on the table.
        """
        if self.current_bet == (0, 0):
            raise ErrorResponse("Bet has not been set.")

        # Total up all the desired type of die
        count = 0
        for player, cup in self.cups:
            count += cup[self.current_bet[1]]
        # Compare it to the bet
        success = count >= self.current_bet[0]

        # Conditionally kick players if we are playing with that rule
        if not success and self.kick_losers:
            self.players.remove(player_id)
            self.cups.pop(player_id)

        self.in_round = False
        return success

    def peek(self, player_id: int) -> list[int]:
        if not self.in_round:
            raise ErrorResponse("Not currently in a round.")
        return self.cups[player_id].copy()


# Liar's Dice Game State
ld_games: dict[int, LiarsDiceGame] = {}  # Map channel IDs to individual games

# region Helper Functions

async def new_game(ctx: discord.Interaction, force: bool = False):
    global ld_games
    if ctx.channel_id in ld_games:
        if ctx.user.id != ld_games[ctx.channel_id].creator:
            raise ErrorResponse("Only the creator of the game can restart it.")
        if not force:
            raise ErrorResponse("A game is already running. Run '/liars force_new' to force a reset.")

    ld_games[ctx.channel_id] = LiarsDiceGame(ctx.user.id)
    await shout(ctx, f"Game was created for {ctx.channel.mention}! Run '/liars join' to be a part of it!")

async def validate_cmd_presence(ctx: discord.Interaction):
    global ld_games
    if ctx.channel_id not in ld_games:
        raise ErrorResponse("There is no game in this channel. Run '/liars new' to make one!")

# endregion

# region Liar's Dice Commands

liars = app_commands.Group(name="liars", description="Commands related to playing the game Liar's Dice.")

@liars.error
async def on_error(ctx: discord.Interaction[discord.Client], err: app_commands.AppCommandError | Exception):
    if isinstance(err, app_commands.errors.CommandInvokeError):
        err = err.original

    if isinstance(err, ErrorResponse):
        message = str(err)
    else:
        message = (f"\nException: {err.__class__.__name__}, "
                   f"Command: {ctx.command.qualified_name if ctx.command else None}, User: {ctx.user}\n")

    await whisper(ctx, message)

@liars.command()
async def new(ctx: discord.Interaction):
    await new_game(ctx)

@liars.command()
async def force_new(ctx: discord.Interaction):
    await new_game(ctx, force=True)

@liars.command()
async def join(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)

    ld_games[ctx.channel_id].join(ctx.user.id)
    await shout(ctx, f"{ctx.user.mention} has joined the game!")

@liars.command()
async def leave(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)

    ld_games[ctx.channel_id].leave(ctx.user.id)
    await shout(ctx, f"{ctx.user.mention} has joined the game!")

@liars.command()
async def start(ctx: discord.Interaction):
    pass

@liars.command(name="raise")
async def raise_bet(ctx: discord.Interaction, dice_count: int, dice_num: int):
    pass

@liars.command(name="call")
async def call_bet(ctx: discord.Interaction):
    pass

# endregion


if __name__ == "__main__":
    ld = LiarsDiceGame(0, 1, 2)
    print(ld.players)
