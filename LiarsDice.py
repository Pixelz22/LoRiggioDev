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
    creator: discord.User  # Discord ID of the creator
    dice_per_player: int  # duh
    dice_sides: int  # What type of dice we playin' with? D6? D20?
    kick_losers: bool  # Do players get kicked from the game when they lose?
    allow_count_reset_on_increment: bool  # Can a player lower the dice count if they raise the dice num?
    all_players: set[discord.User]  # Set of all players present at the end of the game
    live_players: list[discord.User]  # Set of Discord Users of players still in the game
    is_game_finished: bool  # Is the game over?

    # Round Info
    in_round: bool  # are we in the middle of a round?
    round_num: int  # current round number
    raiser_idx: int  # idx of the next player to raise the bet
    current_bet: tuple[int, int]  # The current bet. Format: [dice count, # on the dice], e.g. [2, 3] = 2 Threes
    cups: dict[int, list[int]]  # The cups belonging to each player. cups[player_id][X - 1] = # of Xs that player has

    def __init__(self, creator: discord.User, dice_per_player=5, dice_sides=6,
                 kick_losers=True, allow_count_reset_on_increment=False):
        self.creator = creator
        self.dice_per_player = dice_per_player
        self.dice_sides = dice_sides
        self.kick_losers = kick_losers
        self.allow_count_reset_on_increment = allow_count_reset_on_increment

        self.live_players = []
        self.all_players = set()
        self.cups = dict()
        self.round_num = 0  # We count rounds starting at 1. Fight me.
        self.raiser_idx = 0
        self.in_round = False
        self.is_game_finished = False
        self.join(creator)

    def get_player(self, idx: int) -> discord.User:
        return self.live_players[idx % len(self.live_players)]

    def join(self, player: discord.User):
        if self.round_num > 0:
            raise ErrorResponse("Game has started, cannot add additional players.")
        if player in self.all_players:
            raise ErrorResponse("You are already part of the game.")
        self.live_players.append(player)
        self.all_players.add(player)

    def leave(self, player: discord.User):
        if self.in_round:
            raise ErrorResponse("Cannot leave in the middle of the round.")
        self.live_players.remove(player)
        self.all_players.remove(player)

    def start(self, player: discord.User):
        if player != self.creator:
            raise ErrorResponse("Only the creator can start the game.")
        if self.round_num > 0:
            raise ErrorResponse("Game has already begun!")
        if len(self.all_players) < 2:
            raise ErrorResponse("Cannot begin a game with 1 player.")

        # Shuffle turn order
        new_order = []
        for i in range(len(self.live_players)):
            new_order.append(self.live_players.pop(random.randint(0, len(self.live_players) - 1)))

        self.live_players = new_order

        self.begin_next_round()

    def begin_next_round(self):
        if self.is_game_finished:
            raise ErrorResponse("The game is over. Create a new game using `/liars new` or `/liars reset`.")
        if self.in_round:
            raise ErrorResponse("We're already in the middle of a round.")

        self.round_num += 1
        self.raiser_idx = self.round_num - 1

        for player in self.live_players:
            self.cups[player.id] = [0 for _ in range(self.dice_sides)]
            for die in [random.randint(1, self.dice_sides) for _ in range(self.dice_per_player)]:
                self.cups[player.id][die - 1] += 1

        self.current_bet = 0, 0
        self.in_round = True

    def raise_bet(self, player: discord.User, dice_count: int, dice_num: int):
        # wrap around on raiser_idx is handled here
        if player != self.get_player(self.raiser_idx):
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

    def call_bet(self, player: discord.User) -> str:
        """
        Returns a message containing the details of the call.
        Remember that the bet is if there are AT LEAST X of Y dice on the table.
        """
        if self.current_bet == (0, 0):
            raise ErrorResponse("Bet has not been set.")

        # Total up all the desired type of die
        count_messages = []
        count = 0
        for p in self.live_players:
            p_count = self.cups[p.id][self.current_bet[1] - 1]
            count_messages.append(f"- {p.mention} has {p_count} {self.current_bet[1]}s.\n")
            count += p_count
        # Compare it to the bet
        bet_was_met = count >= self.current_bet[0]

        last_raiser = self.get_player(self.raiser_idx - 1)

        # Construct the result message
        dice_count_msg = ''.join(count_messages)
        result_msg = (f"{player.mention}, the bet holds! You're out!" if bet_was_met
                      else f"{last_raiser.mention}, you're a liar! You're out!")
        msg = (f"{player.mention} has called the bet! Here are the results:\n"
               f"{dice_count_msg}\n"
               f"That's a total of {count} {self.current_bet[1]}s! {result_msg}\n\n")

        # Conditionally kick players if we are playing with that rule
        if self.kick_losers:
            # Kick either the caller or the last person to raise
            player_to_kick = player if bet_was_met else last_raiser
            self.live_players.remove(player_to_kick)
            self.cups.pop(player_to_kick.id)

            if len(self.live_players) <= 1:
                self.is_game_finished = True

        self.in_round = False

        return msg

    def peek(self, player: discord.User) -> list[int]:
        if self.round_num < 1:
            raise ErrorResponse("No dice have been thrown yet.")
        dice = []
        for dice_num, dice_count in enumerate(self.cups[player.id]):
            for _ in range(dice_count):
                dice.append(dice_num + 1)
        return dice

    def add_state_embed(self, embed: discord.Embed):
        turn_order_str = ""
        for i in range(len(self.live_players)):
            idx = self.round_num - 1 + i  # Offset it so that first player in embed was the one who sets the bet
            player = self.get_player(idx)
            player_name = (f"*{player.display_name}*" if idx == self.raiser_idx % len(self.live_players) and self.in_round
                           else player.display_name)
            turn_order_str += f"{i + 1}. {player_name}\n"
        embed.add_field(name="Turn Order:", value=turn_order_str)

        current_bet_str = (f"{self.current_bet[0]} {self.current_bet[1]}s" if self.current_bet != (0, 0)
                           else "Bet hasn't been set")
        embed.add_field(name="Current Bet:", value=current_bet_str)


# Liar's Dice Game State
ld_games: dict[int, LiarsDiceGame] = {}  # Map channel IDs to individual games


# region Helper Functions

async def new_game(ctx: discord.Interaction, force: bool = False):
    global ld_games
    if ctx.channel_id in ld_games and not ld_games[ctx.channel_id].is_game_finished:
        if ctx.user != ld_games[ctx.channel_id].creator:
            raise ErrorResponse("Only the creator of the game can restart it.")
        if not force:
            raise ErrorResponse("A game is already running. Run `/liars force_new` to force a new game.")

    ld_games[ctx.channel_id] = LiarsDiceGame(ctx.user)
    await shout(ctx, f"Game was created for {ctx.channel.mention}! "
                 f"Run `/liars join` to be a part of it, and `/liars start` to begin the game!")


async def reset_game(ctx: discord.Interaction, force: bool = False):
    global ld_games
    if ctx.channel_id not in ld_games:
        raise ErrorResponse("No previous game has been played")

    if not ld_games[ctx.channel_id].is_game_finished:
        if ctx.user != ld_games[ctx.channel_id].creator:
            raise ErrorResponse("Only the creator of the game can restart it.")
        if not force:
            raise ErrorResponse("A game is already running. Run `/liars force_new` to force a new game.")

    old_game = ld_games[ctx.channel_id]
    ld_games[ctx.channel_id] = LiarsDiceGame(ctx.user)
    # Add all previous players to game
    for player in old_game.all_players:
        ld_games[ctx.channel_id].join(player)

    await shout(ctx, f"Game was created for {ctx.channel.mention}! "
                     f"Run `/liars join` to be a part of it, and `/liars start` to begin the game!")


async def validate_cmd_presence(ctx: discord.Interaction, ignore_user=False):
    global ld_games
    if ctx.channel_id not in ld_games:
        raise ErrorResponse("There is no game in this channel. Run `/liars new` to make one!")
    if not ignore_user and ctx.user not in ld_games[ctx.channel_id].all_players:
        raise ErrorResponse(f"You are not a part of the {ctx.channel.mention} Liar's Dice game. "
                            f"Run `/liars join` to join the fun!")


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
async def reset(ctx: discord.Interaction):
    await reset_game(ctx)


@ld_group.command()
async def force_reset(ctx: discord.Interaction):
    await reset_game(ctx, force=True)


@ld_group.command()
async def join(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx, ignore_user=True)

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

    game.start(ctx.user)

    embed = discord.Embed(title="Liar's Dice",
                          description="The die is cast, the round begun!")
    game.add_state_embed(embed)
    await shout(ctx, embed=embed)


@ld_group.command(name="continue")
async def next_round(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    if game.round_num == 0:
        raise ErrorResponse("Game has not yet begun. Have the game creator call `/liars start`.")

    game.begin_next_round()

    embed = discord.Embed(title="Liar's Dice",
                          description="The die is cast, the round begun!")
    game.add_state_embed(embed)
    await shout(ctx, embed=embed)


@ld_group.command(name="raise")
async def raise_bet(ctx: discord.Interaction, dice_count: int, dice_num: int):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    game.raise_bet(ctx.user, dice_count, dice_num)
    await shout(ctx, f"{ctx.user.mention} has raised the bet to {dice_count} {dice_num}s. "
                     f"Next to raise is {game.get_player(game.raiser_idx).mention}.")


@ld_group.command(name="call")
async def call_bet(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    result_msg = game.call_bet(ctx.user)
    await shout(ctx, result_msg)
    if not game.is_game_finished:
        await shout(ctx, f"Run `/liars continue` to move to the next round")
    else:
        await shout(ctx, f"And the game is over! "
                         f"{game.get_player(0).mention}, congratulations! You're the winner!\n"
                         f"To prepare a new game with the same people, have the game creator run `/liars reset`.")


@ld_group.command()
async def peek(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    dice = game.peek(ctx.user)
    await whisper(ctx, str(dice), delete_after=60)


@ld_group.command()
async def state(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    embed = discord.Embed(title="Liar's Dice", description="")
    game.add_state_embed(embed)
    await whisper(ctx, embed=embed)


# endregion
