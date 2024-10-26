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
    creator: discord.User                 # Discord ID of the creator
    dice_per_player: int                  # duh
    dice_sides: int                       # What type of dice we playin' with? D6? D20?
    kick_losers: bool                     # Do players get kicked from the game when they lose?
    allow_count_reset_on_increment: bool  # Can a player lower the dice count if they raise the dice num?
    players: list[discord.User]           # Set of Discord Users of players in the game

    # Round Info
    in_round: bool                # are we in the middle of a round?
    round_num: int                # current round number
    raiser_idx: int               # idx of the next player to raise the bet
    current_bet: tuple[int, int]  # The current bet. Format: [dice count, # on the dice], e.g. [2, 3] = 2 Threes
    cups: dict[int, list[int]]    # The cups belonging to each player. cups[player_id][X - 1] = # of Xs that player has

    def __init__(self, creator: discord.User, dice_per_player=5, dice_sides=6,
                 kick_losers=True, allow_count_reset_on_increment=False):
        self.creator = creator
        self.dice_per_player = dice_per_player
        self.dice_sides = dice_sides
        self.kick_losers = kick_losers
        self.allow_count_reset_on_increment = allow_count_reset_on_increment

        self.players = []
        self.cups = dict()
        self.round_num = 0  # We count rounds starting at 1. Fight me.
        self.raiser_idx = 0
        self.in_round = False
        self.join(creator)

    def join(self, player: discord.User):
        if self.round_num > 0:
            raise ErrorResponse("Game has started, cannot add additional players.")
        if player in self.players:
            raise ErrorResponse("You are already part of the game.")
        self.players.append(player)

    def leave(self, player: discord.User):
        if self.in_round:
            raise ErrorResponse("Cannot leave in the middle of the round.")
        if player not in self.players:
            raise ErrorResponse("You aren't part of the game.")
        self.players.remove(player)

    def begin_next_round(self):
        if self.in_round:
            raise ErrorResponse("Already in a round.")

        self.round_num += 1
        self.raiser_idx = self.round_num - 1

        for player in self.players:
            self.cups[player.id] = [0 for _ in range(self.dice_sides)]
            for die in [random.randint(1, self.dice_sides) for _ in range(self.dice_per_player)]:
                self.cups[player.id][die - 1] += 1

        self.current_bet = 0, 0
        self.in_round = True

    def raise_bet(self, player: discord.User, dice_count: int, dice_num: int):
        if player != self.players[self.raiser_idx % len(self.players)]:  # wrap around on raiser_idx is handled here
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

    def call_bet(self, player: discord.User) -> bool:
        """
        Returns whether bet was true.
        Remember that the bet is if there are AT LEAST X of Y dice on the table.
        """
        if self.current_bet == (0, 0):
            raise ErrorResponse("Bet has not been set.")

        # Total up all the desired type of die
        count = 0
        for player, cup in self.cups.items():
            count += cup[self.current_bet[1] - 1]
        # Compare it to the bet
        bet_was_met = count >= self.current_bet[0]

        # Conditionally kick players if we are playing with that rule
        if self.kick_losers:
            # Kick either the caller or the last person to raise
            player_to_kick = player if bet_was_met else self.players[(self.raiser_idx - 1) % len(self.players)]
            self.players.remove(player_to_kick)
            self.cups.pop(player_to_kick.id)

        self.in_round = False
        return bet_was_met

    def peek(self, player: discord.User) -> list[int]:
        if not self.in_round:
            raise ErrorResponse("Not currently in a round.")
        dice = []
        for dice_num, dice_count in enumerate(self.cups[player.id]):
            for _ in range(dice_count):
                dice.append(dice_num + 1)
        return dice

    def add_turn_embed(self, embed: discord.Embed):
        turn_order_str = ""
        for i, player in enumerate(self.players):
            player_name = (f"**{player.display_name}**" if i == self.raiser_idx % len(self.players) and self.in_round
                           else player.display_name)
            turn_order_str += f"\- {player_name}\n"
        embed.add_field(name="Turn Order:", value=turn_order_str)


# Liar's Dice Game State
ld_games: dict[int, LiarsDiceGame] = {}  # Map channel IDs to individual games

# region Helper Functions

async def new_game(ctx: discord.Interaction, force: bool = False):
    global ld_games
    if ctx.channel_id in ld_games:
        if ctx.user != ld_games[ctx.channel_id].creator:
            raise ErrorResponse("Only the creator of the game can restart it.")
        if not force:
            raise ErrorResponse("A game is already running. Run `/liars force_new` to force a reset.")

    ld_games[ctx.channel_id] = LiarsDiceGame(ctx.user)
    await shout(ctx, f"Game was created for {ctx.channel.mention}! Run `/liars join` to be a part of it!")

async def validate_cmd_presence(ctx: discord.Interaction):
    global ld_games
    if ctx.channel_id not in ld_games:
        raise ErrorResponse("There is no game in this channel. Run '/liars new' to make one!")

# endregion

# region Liar's Dice Commands

ld_group = app_commands.Group(name="liars", description="Commands related to playing the game Liar's Dice.")

@ld_group.error
async def on_error(ctx: discord.Interaction[discord.Client], err: app_commands.AppCommandError | Exception):
    if isinstance(err, app_commands.errors.CommandInvokeError):
        err = err.original

    if isinstance(err, ErrorResponse):
        await whisper(ctx, str(err))
    else:
        message = (f"\nException: {err.__class__.__name__}, "
                   f"Command: {ctx.command.qualified_name if ctx.command else None}, User: {ctx.user}\n"
                   f"Description: {err}\n")
        await whisper(ctx, message, delete_after=None)


@ld_group.command()
async def new(ctx: discord.Interaction):
    await new_game(ctx)

@ld_group.command()
async def force_new(ctx: discord.Interaction):
    await new_game(ctx, force=True)

@ld_group.command()
async def join(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)

    ld_games[ctx.channel_id].join(ctx.user)
    await shout(ctx, f"{ctx.user.mention} has joined the game!")

@ld_group.command()
async def leave(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)

    ld_games[ctx.channel_id].leave(ctx.user)
    await shout(ctx, f"{ctx.user.mention} has left the game.")

@ld_group.command()
async def start(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    if ctx.user != game.creator:
        raise ErrorResponse("Only the creator can start the game.")
    if game.round_num > 0:
        raise ErrorResponse("Game has already begun!")

    game.begin_next_round()

    embed = discord.Embed(title="Liar's Dice",
                          description="The die is cast, the round begun!")
    game.add_turn_embed(embed)
    await shout(ctx, embed=embed)


@ld_group.command()
async def next_round(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    if game.round_num == 0:
        raise ErrorResponse("Game has not yet begun. Have the game creator call `/liars start`.")
    if game.in_round:
        raise ErrorResponse("You're in the middle of a round!")

    game.begin_next_round()

    embed = discord.Embed(title="Liar's Dice",
                          description="The die is cast, the round begun!")
    game.add_turn_embed(embed)
    await shout(ctx, embed=embed)

@ld_group.command(name="raise")
async def raise_bet(ctx: discord.Interaction, dice_count: int, dice_num: int):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    game.raise_bet(ctx.user, dice_count, dice_num)
    await shout(ctx, f"{ctx.user.mention} has raised the bet to {dice_count} {dice_num}s")

@ld_group.command(name="call")
async def call_bet(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    success = game.call_bet(ctx.user)
    await shout(ctx, f"Bet was called! Did the bet hold: {success}")

@ld_group.command()
async def peek(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    dice = game.peek(ctx.user)
    await whisper(ctx, str(dice))

@ld_group.command()
async def turns(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    embed = discord.Embed(title="Liar's Dice", description="")
    game.add_turn_embed(embed)
    await whisper(ctx, embed=embed)

# endregion


if __name__ == "__main__":
    ld = LiarsDiceGame(0, 1, 2)
    print(ld.players)
