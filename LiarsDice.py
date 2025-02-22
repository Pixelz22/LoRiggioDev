import random
from enum import Enum

import discord
from discord import app_commands, Interaction, Client

from utils import whisper, shout


class ErrorResponse(RuntimeError):
    def __init__(self, msg):
        super().__init__(msg)


class LiarsDiceGameMode(Enum):
    LAST_MAN_STANDING = 1
    FIRST_ELIMINATION = 2
    SUDDEN_DEATH = 3
    INFINITE = 4

    def __str__(self):
        return self.name.replace('_', ' ').title()


GAMEMODE_CONVERSION: dict[str, LiarsDiceGameMode] = {mode.name: mode for mode in LiarsDiceGameMode}

# region Emoji Stuff

my_emojis: dict[str, discord.Emoji] = {}

die_colors = ["red"]


def load_emojis(client: discord.Client):
    global my_emojis
    # load d6
    for i in range(1, 7):
        for color in die_colors:
            emoji = discord.utils.get(client.emojis, name=f"d6_{color}_{i}")
            my_emojis[emoji.name] = emoji


def stringify_die(die: int) -> str:
    if die <= 6:
        # Use the d6 custom emojis
        return str(my_emojis[f"d6_{random.choice(die_colors)}_{die}"])
    else:
        return str(die)


def stringify_cup(cup: list[int]) -> str:
    msg = ""
    for die in cup:
        msg = f"{msg} {stringify_die(die)}"
    return msg


# endregion


class LiarsDicePlayerState:
    num_dice: int  # how many dice this player has left
    loss_count: int  # How many times this player has lost a round
    cup: list[int]  # The cup belonging to this player. cup[X - 1] = # of Xs this player has

    def __init__(self, game):
        self.game = game  # Have to define it without strong typing because Python doesn't have good forward declaration
        self.num_dice = game.dice_per_player
        self.loss_count = 0

    def cast_dice(self):
        self.cup = [0 for i in range(self.game.dice_sides)]
        for die in [random.randint(1, self.game.dice_sides) for _ in range(self.num_dice)]:
            self.cup[die - 1] += 1


class LiarsDiceGame:
    # Game Info
    creator: discord.User  # Discord ID of the creator?
    all_players: set[discord.User]  # Set of all players present at the end of the game
    live_players: list[discord.User]  # List of Discord Users of players still in the game, used to maintain turn order
    player_states = dict[int, LiarsDicePlayerState]  # The state of each player in the game
    is_game_finished: bool  # Is the game over?

    # Matchmaking
    queued_to_join: list[discord.User]  # list of players to join the game next round

    # Game Settings
    dice_per_player: int  # duh
    dice_sides: int  # What type of dice we playin' with? D6? D20?
    gamemode: LiarsDiceGameMode  # What version of the game are we playing
    allow_count_reset_on_increment: bool  # Can a player lower the dice count if they raise the dice num

    # Round Info
    in_round: bool  # are we in the middle of a round?
    round_num: int  # current round number
    raiser_idx: int  # idx of the next player to raise the bet
    current_bet: tuple[int, int]  # The current bet. Format: [dice count, # on the dice], e.g. [2, 3] = 2 Threes

    def __init__(self, creator: discord.User, dice_per_player=5, dice_sides=6,
                 gamemode=LiarsDiceGameMode.FIRST_ELIMINATION, allow_count_reset_on_increment=False):
        self.creator = creator
        self.dice_per_player = dice_per_player
        self.dice_sides = dice_sides
        self.gamemode = gamemode
        self.allow_count_reset_on_increment = allow_count_reset_on_increment

        self.all_players = set()
        self.queued_to_join = list()
        self.reset()
        self.join(creator)

    def reset(self):
        self.live_players = list(self.all_players)
        self.round_num = 0  # We count rounds starting at 1. Fight me.
        self.raiser_idx = 0
        self.current_bet = 0, 0
        self.in_round = False
        self.is_game_finished = False
        self.player_states = {player.id: LiarsDicePlayerState(self)
                              for player in self.all_players}

    def is_game_started(self) -> bool:
        return self.round_num > 0

    def is_player_present(self, player: discord.User, allow_queued_players: bool = False):
        return player in self.all_players or (allow_queued_players and player in self.queued_to_join)

    def get_player(self, idx: int) -> discord.User:
        return self.live_players[idx % len(self.live_players)]

    def join(self, player: discord.User):
        if player in self.all_players or player in self.queued_to_join:
            raise ErrorResponse("You are already part of the game.")
        self.queued_to_join.append(player)

    def leave(self, player: discord.User):
        if player in self.all_players:
            if self.in_round:
                raise ErrorResponse("Cannot leave in the middle of the round.")
            self.live_players.remove(player)
            self.all_players.remove(player)
            self.player_states.pop(player.id)
        elif player in self.queued_to_join:
            self.queued_to_join.remove(player)
        else:
            raise ErrorResponse("You aren't part of the game.")

    def start(self, player: discord.User):
        if player != self.creator:
            raise ErrorResponse("Only the creator can start the game.")
        if self.round_num > 0:
            raise ErrorResponse("Game has already begun!")
        if len(self.all_players) + len(self.queued_to_join) < 1:
            raise ErrorResponse("Cannot begin a game with 1 players.")

        self.begin_next_round()

    def end_game(self) -> discord.Embed:
        if not self.is_game_started():
            raise ErrorResponse("The game has not even begun!")
        if self.in_round:
            raise ErrorResponse("We're in the middle of a round!")

        self.is_game_finished = True
        embed = discord.Embed(title="Liar's Dice: Final Results",
                              description="The game is over! Here are everyone's final scores")

        scores_msg = ''.join([f"- {player.mention}: Lost {self.player_states[player.id].loss_count} times\n"
                              for player in self.all_players])
        embed.add_field(name="", value=scores_msg)

        return embed

    def begin_next_round(self):
        if self.is_game_finished:
            raise ErrorResponse("The game is over. Create a new game using `/liars new` or `/liars reset`.")
        if self.in_round:
            raise ErrorResponse("We're already in the middle of a round.")

        # Add any new players to the game
        for p in self.queued_to_join:
            self.all_players.add(p)
            self.live_players.insert(random.randint(0, len(self.live_players)), p)
            self.player_states[p.id] = LiarsDicePlayerState(self)
        self.queued_to_join.clear()

        self.round_num += 1
        self.raiser_idx = self.round_num - 1

        # Cast the dice for players still in the game
        for player in self.live_players:
            self.player_states[player.id].cast_dice()

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

    def call_bet(self, player: discord.User) -> discord.Embed:
        """
        Returns a message containing the details of the call.
        Remember that the bet is if there are AT LEAST X of Y dice on the table.
        """
        if self.current_bet == (0, 0):
            raise ErrorResponse("Bet has not been set.")
        if not self.in_round:
            raise ErrorResponse("You aren't currently in a round.")

        # Total up all the desired type of die
        count_messages = []
        final_hands_messages = []
        count = 0
        for p in self.live_players:
            p_count = self.player_states[p.id].cup[self.current_bet[1] - 1]
            final_hands_messages.append(f"- {p.mention}: {stringify_cup(self.peek(p))}\n")
            count_messages.append(f"- {p.mention} has {p_count} {stringify_die(self.current_bet[1])}s\n")
            count += p_count
        # Compare it to the bet
        bet_was_met = count >= self.current_bet[0]

        last_raiser = self.get_player(self.raiser_idx - 1)

        embed = discord.Embed(title="Liar's Dice",
                              description=f"{player.mention} has called the bet! Here are the results:")

        # Construct the result message
        dice_count_msg = ''.join(count_messages)
        final_hands_msg = ''.join(final_hands_messages)
        result_msg = f"That's {count} {stringify_die(self.current_bet[1])}s. " + (
            f"{player.mention}, the bet holds! You're out!" if bet_was_met
            else f"{last_raiser.mention}, you're a liar! You're out!")

        embed.add_field(name="Everyone's Cups:", value=final_hands_msg)
        embed.add_field(name="Dice Counts:", value=dice_count_msg)
        embed.add_field(name="Results:", value=result_msg, inline=False)

        # Conditionally kick players if we are playing with that rule
        player_who_lost = player if bet_was_met else last_raiser
        self.on_player_lose(player_who_lost)
        self.in_round = False

        return embed

    def on_player_lose(self, player: discord.User):
        if self.gamemode == LiarsDiceGameMode.SUDDEN_DEATH:
            # Kick the player who lost
            self.live_players.remove(player)

            if len(self.live_players) <= 1:
                self.is_game_finished = True
            return
        ps = self.player_states[player.id]
        if self.gamemode == LiarsDiceGameMode.LAST_MAN_STANDING:
            ps.loss_count += 1
            ps.num_dice -= 1
            if ps.num_dice <= 0:
                # Kick the player if they're out of dice
                self.live_players.remove(player)

                if len(self.live_players) <= 1:
                    self.is_game_finished = True
        elif self.gamemode == LiarsDiceGameMode.FIRST_ELIMINATION:
            ps.loss_count += 1
            ps.num_dice -= 1
            if ps.num_dice <= 0:
                self.is_game_finished = True
        elif self.gamemode == LiarsDiceGameMode.INFINITE:
            ps.loss_count += 1

    def peek(self, player: discord.User) -> list[int]:
        if self.round_num < 1:
            raise ErrorResponse("No dice have been thrown yet.")
        dice = []
        for dice_num, dice_count in enumerate(self.player_states[player.id].cup):
            for _ in range(dice_count):
                dice.append(dice_num + 1)
        return dice

    def add_state_embed(self, embed: discord.Embed):
        embed.add_field(name="Mode:", value=str(self.gamemode), inline=False)
        if self.is_game_started():
            turn_order_str = ""
            for i in range(len(self.live_players)):
                idx = self.round_num - 1 + i  # Offset it so that first player in embed was the one who sets the bet
                player = self.get_player(idx)
                player_name = (
                    f"*{player.display_name}*" if idx == self.raiser_idx % len(self.live_players) and self.in_round
                    else player.display_name)
                turn_order_str += f"{i + 1}. {player_name}\n"
            embed.add_field(name="Turn Order:", value=turn_order_str)

            current_bet_str = (f"{self.current_bet[0]} {stringify_die(self.current_bet[1])}s"
                               if self.current_bet != (0, 0) else "Bet hasn't been set")
            embed.add_field(name="Current Bet:", value=current_bet_str)
        else:
            embed.description = "The game has not yet started."
            players_msg = ''.join([f"- {player.mention}\n" for player in self.all_players])
            embed.add_field(name="Players:", value=players_msg)

    def create_view(self):  # Can't do return declaration because Python lacks good forward declaration
        return LiarsDiceView(self)


# region UI Components

class LiarsDiceView(discord.ui.View):
    game: LiarsDiceGame  # The game this view belongs to

    def __init__(self, game: LiarsDiceGame):
        super().__init__()
        self.game = game
        self.on_error = lambda interaction, err, item: on_error(interaction, err)

    def add_gameplay_bar(self):
        if self.game.is_game_started():
            peek_btn = discord.ui.Button(label="Peek")
            peek_btn.callback = peek.callback
            self.add_item(peek_btn)

            if self.game.current_bet != (0, 0):
                call_btn = discord.ui.Button(label="Call", style=discord.ButtonStyle.primary)
                call_btn.callback = call_bet.callback
                self.add_item(call_btn)

        else:
            self.add_start_bar()
        return self

    def add_start_bar(self):
        join_btn = discord.ui.Button(label="Join Game")
        join_btn.callback = join.callback
        leave_btn = discord.ui.Button(label="Leave Game")
        leave_btn.callback = leave.callback
        start_btn = discord.ui.Button(label="Start!", style=discord.ButtonStyle.primary)
        start_btn.callback = start.callback

        self.add_item(join_btn)
        self.add_item(leave_btn)
        self.add_item(start_btn)

        return self

    def add_continue_bar(self):
        continue_btn = discord.ui.Button(label="Continue", style=discord.ButtonStyle.primary)
        continue_btn.callback = next_round.callback
        self.add_item(continue_btn)

        if self.game.gamemode == LiarsDiceGameMode.INFINITE:
            end_btn = discord.ui.Button(label="End Game")
            end_btn.callback = end.callback
            self.add_item(end_btn)

        return self

    def add_end_bar(self):
        reset_btn = discord.ui.Button(label="Play again", style=discord.ButtonStyle.primary)
        reset_btn.callback = reset.callback

        self.add_item(reset_btn)

        return self

    def add_mode_dropdown(self):
        self.add_item(ModeDropdown(self.game, row=0))
        return self


class ModeDropdown(discord.ui.Select):
    game: LiarsDiceGame  # The game this dropdown belongs to

    def __init__(self, game: LiarsDiceGame, row: int = None):
        super().__init__(row=row, options=[
            discord.SelectOption(emoji=f"🎲", label=f"First Elimination",
                                 description="Standard dice elimination, ends after first player is out.",
                                 value=LiarsDiceGameMode.FIRST_ELIMINATION.name,
                                 default=game.gamemode == LiarsDiceGameMode.FIRST_ELIMINATION),
            discord.SelectOption(emoji=f"🥾", label=f"Last Man Standing",
                                 description="Standard dice elimination, ends when one player remains.",
                                 value=LiarsDiceGameMode.LAST_MAN_STANDING.name,
                                 default=game.gamemode == LiarsDiceGameMode.LAST_MAN_STANDING),
            discord.SelectOption(emoji=f"☠️", label=f"Sudden Death",
                                 description="When a player loses, they are kicked from the table.",
                                 value=LiarsDiceGameMode.SUDDEN_DEATH.name,
                                 default=game.gamemode == LiarsDiceGameMode.SUDDEN_DEATH),
            discord.SelectOption(emoji=f"🔄", label=f"Infinite Mode",
                                 description="Game continues indefinitely.",
                                 value=LiarsDiceGameMode.INFINITE.name,
                                 default=game.gamemode == LiarsDiceGameMode.INFINITE)
        ])
        self.game = game

    async def interaction_check(self, interaction: Interaction[Client], /) -> bool:
        if interaction.user != self.game.creator:
            await whisper(interaction, "Only the game creator can change the settings.")
            return False
        return True

    async def callback(self, interaction: Interaction[Client]):
        await interaction.response.defer()
        assert interaction.data is not None and "custom_id" in interaction.data, "Invalid interaction data"
        self.game.gamemode = GAMEMODE_CONVERSION[self.values[0]]


# endregion


# Liar's Dice Game State
ld_games: dict[int, LiarsDiceGame] = {}  # Map channel IDs to individual games


# region Helper Functions

async def new_game(ctx: discord.Interaction, force: bool = False):
    global ld_games
    if ctx.channel_id in ld_games and not ld_games[ctx.channel_id].is_game_finished:
        if not (ctx.user == ld_games[ctx.channel_id].creator or ctx.user.guild_permissions.administrator):
            raise ErrorResponse("Only the creator of the game or a server admin can restart it.")
        if not force:
            raise ErrorResponse("A game is already running. Run `/liars force_new` to force a new game.")

    ld_games[ctx.channel_id] = LiarsDiceGame(ctx.user)
    game = ld_games[ctx.channel_id]

    await shout(ctx, f"Game was created for {ctx.channel.mention}! "
                     f"Use the buttons below to join, leave, or start!",
                view=LiarsDiceView(game).add_mode_dropdown().add_start_bar())


async def reset_game(ctx: discord.Interaction, force: bool = False):
    global ld_games
    if ctx.channel_id not in ld_games:
        raise ErrorResponse("No previous game has been played")

    if not ld_games[ctx.channel_id].is_game_finished:
        if not (ctx.user == ld_games[ctx.channel_id].creator or ctx.user.guild_permissions.administrator):
            raise ErrorResponse("Only the creator of the game or a server admin can restart it.")
        if not force:
            raise ErrorResponse("A game is already running. Run `/liars force_reset` to force a new game.")

    game = ld_games[ctx.channel_id]
    game.creator = ctx.user  # Re-assign the creator (allows admins to steal back the game)
    game.reset()

    await shout(ctx, f"Game was reset for {ctx.channel.mention} with all the old players! "
                     f"Use the buttons below to start the game!",
                view=LiarsDiceView(game).add_mode_dropdown().add_start_bar())


async def validate_cmd_presence(ctx: discord.Interaction, ignore_user=False, allow_queued_players=False):
    global ld_games
    if ctx.channel_id not in ld_games:
        raise ErrorResponse("There is no game in this channel. Run `/liars new` to make one!")
    if (not ignore_user and
            not ld_games[ctx.channel_id].is_player_present(ctx.user, allow_queued_players=allow_queued_players)):
        raise ErrorResponse(f"You are not a part of the {ctx.channel.mention} Liar's Dice game. "
                            f"Run `/liars join` to join the fun!")


# endregion


# region Liar's Dice Commands

ld_group = app_commands.Group(name="liars", description="Commands related to playing the game Liar's Dice.")


async def interaction_check(ctx: discord.Interaction) -> bool:
    if ctx.guild is None:
        await shout(ctx, "I'm sorry, but you can't run this game in a DM. Try running it in a server!")
        return False
    return True


# Apparently this works better than the decorator
ld_group.interaction_check = interaction_check
ld_group.guild_only = True


@ld_group.error
async def on_error(ctx: discord.Interaction[discord.Client], err: app_commands.AppCommandError | Exception):
    if isinstance(err, app_commands.errors.CommandInvokeError):
        err = err.original

    if isinstance(err, discord.app_commands.CheckFailure):
        return

    if isinstance(err, ErrorResponse):
        await whisper(ctx, str(err))
    else:
        message = (f"\nException: {err.__class__.__name__}, "
                   f"Command: {ctx.command.qualified_name if ctx.command else None}, User: {ctx.user}\n"
                   f"Description: {err}\n")
        await whisper(ctx, message, delete_after=None)


@ld_group.command(name="help", description="Pulls up the manual!")
async def help_cmd(ctx: discord.Interaction):
    global ld_games
    global my_emojis

    embed = discord.Embed(title="Liar's Dice Bot Manual",
                          description=f"Here are some helpful commands for interacting with the bot! {stringify_die(5)}")
    cmd_descriptions = ''.join([f"- */liars {cmd.name}*: {cmd.description}\n" for cmd in ld_group.walk_commands()])
    embed.add_field(name="Command List:", value=cmd_descriptions)

    await shout(ctx, embed=embed)


@ld_group.command(description="Start a new game! Note you can have one distinct game per text channel.")
async def new(ctx: discord.Interaction):
    await new_game(ctx)


@ld_group.command(description="Force a new game to be created, even if one already exists.")
async def force_new(ctx: discord.Interaction):
    await new_game(ctx, force=True)


@ld_group.command(description="Reset the game with the same players.")
async def reset(ctx: discord.Interaction):
    await reset_game(ctx)


@ld_group.command(description="Force a game to reset, even if the game is already exists.")
async def force_reset(ctx: discord.Interaction):
    await reset_game(ctx, force=True)


@ld_group.command(description="Join the game for the channel you called the command in, if it exists.")
async def join(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx, ignore_user=True)

    ld_games[ctx.channel_id].join(ctx.user)
    await shout(ctx, f"{ctx.user.mention} has joined the game!")


@ld_group.command(description="Leave the game for the channel you called the command in.")
async def leave(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx, allow_queued_players=True)

    ld_games[ctx.channel_id].leave(ctx.user)
    await shout(ctx, f"{ctx.user.mention} has left the game.")


@ld_group.command(description="Start the game for the channel you called the command in.")
async def start(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx, allow_queued_players=True)
    game = ld_games[ctx.channel_id]

    game.start(ctx.user)

    embed = discord.Embed(title="Liar's Dice",
                          description=f"The die is cast, the round begun! "
                                      f"{game.get_player(game.raiser_idx).mention}, you set the bet!\n"
                                      f"Use '/liars raise'.")
    game.add_state_embed(embed)

    await shout(ctx, embed=embed, view=LiarsDiceView(game).add_gameplay_bar())


@ld_group.command(description="Get information about the state of the game.")
async def info(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx, ignore_user=True)
    game = ld_games[ctx.channel_id]

    embed = discord.Embed(title="Liar's Dice", description="")
    game.add_state_embed(embed)

    await whisper(ctx, embed=embed, view=LiarsDiceView(game).add_gameplay_bar())


@ld_group.command(name="continue", description="Begin the next round of the game.")
async def next_round(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    if game.round_num == 0:
        raise ErrorResponse("Game has not yet begun. Have the game creator call `/liars start`.")

    game.begin_next_round()

    embed = discord.Embed(title="Liar's Dice",
                          description="The die is cast, the round begun! "
                                      f"{game.get_player(game.raiser_idx).mention}, you set the bet.")
    game.add_state_embed(embed)

    await shout(ctx, embed=embed, view=LiarsDiceView(game).add_gameplay_bar())


@ld_group.command(description="Take a look at your cup.")
async def peek(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    dice = game.peek(ctx.user)
    await whisper(ctx, stringify_cup(dice), delete_after=60)


@ld_group.command(name="raise", description="Raise the bet! "
                                            "First number is the number of dice, "
                                            "second number is the number on the dice.")
async def raise_bet(ctx: discord.Interaction, dice_count: int, dice_num: int):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    game.raise_bet(ctx.user, dice_count, dice_num)

    await shout(ctx, f"{ctx.user.mention} has raised the bet to {dice_count} {stringify_die(dice_num)}s. "
                     f"Next to raise is {game.get_player(game.raiser_idx).mention}.",
                view=LiarsDiceView(game).add_gameplay_bar())


@ld_group.command(name="call", description="12 fives... Call me a liar.")
async def call_bet(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    result = game.call_bet(ctx.user)
    view = LiarsDiceView(game)
    await shout(ctx, embed=result)
    if game.gamemode == LiarsDiceGameMode.INFINITE:
        await shout(ctx, f"Use the buttons below to continue to the next round or end the game.",
                    view=view.add_continue_bar())
    else:
        if not game.is_game_finished:
            await shout(ctx, f"Press the button below to move on to the next round.", view=view.add_continue_bar())
        else:
            await shout(ctx, f"And the game is over! "
                             f"{game.get_player(0).mention}, congratulations! You're the winner!\n"
                             f"To prepare a new game with the same people, press the button below.",
                        view=view.add_end_bar())


@ld_group.command(description="Forcibly end the game.")
async def end(ctx: discord.Interaction):
    global ld_games
    await validate_cmd_presence(ctx)
    game = ld_games[ctx.channel_id]

    if not (ctx.user == game.creator or ctx.user.guild_permissions.administrator):
        raise ErrorResponse("Only the game creator or an admin can end the game.")

    result = game.end_game()
    await shout(ctx, embed=result)
    await shout(ctx, f"To prepare a new game with the same people, press the button below.",
                view=LiarsDiceView(game).add_end_bar())

# endregion
