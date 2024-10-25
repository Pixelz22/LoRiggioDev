import random


class LiarsDiceGame:
    # Game info
    dice_per_player: int                  # duh
    dice_sides: int                       # What type of dice we playin' with? D6? D20?
    kick_losers: bool                     # Do players get kicked from the game when they lose?
    allow_count_reset_on_increment: bool  # Can a player lower the dice count if they raise the dice num?
    players: list[int]                     # Set of discord IDs of players in the game

    # Round info
    in_round: bool                # are we in the middle of a round?
    round_num: int                # current round number
    caller_idx: int               # idx of the next player to call/raise the bet
    current_bet: tuple[int, int]  # The current bet. Format: [dice count, # on the dice], e.g. [2, 3] = Two 3s
    cups: dict[int, list[int]]    # The cups belonging to each player. cups[player_id][X] = # of Xs that player has

    def __init__(self, *player_ids, dice_per_player=5, dice_sides=6,
                 kick_losers=True, allow_count_reset_on_increment=False):
        self.dice_per_player = dice_per_player
        self.dice_sides = dice_sides
        self.kick_losers = kick_losers
        self.allow_count_reset_on_increment = allow_count_reset_on_increment

        self.players = []
        self.cups = dict()
        self.round_num = 0  # We count rounds starting at 1. Fight me.
        self.in_round = False
        self.add_players(player_ids)

    def add_players(self, *player_ids):
        if self.round_num > 0:
            raise ValueError("Game has started, cannot add additional players")
        for ID in player_ids:
            if type(ID) is not int:
                raise ValueError("Player IDs must be ints")
            self.players.append(ID)

    def begin_next_round(self):
        if self.in_round:
            raise RuntimeError("Already in a round.")

        self.round_num += 1
        self.caller_idx = self.round_num - 1

        for player in self.players:
            self.cups[player] = [0 for _ in range(self.dice_sides)]
            for die in [random.randint(1, self.dice_sides) for _ in range(self.dice_per_player)]:
                self.cups[player][die] += 1

        self.current_bet = 0, 0
        self.in_round = True

    def raise_bet(self, player_id: int, dice_count: int, dice_num: int):
        if player_id != self.players[self.caller_idx]:  # wrap around on caller_idx is handled here
            raise ValueError(f"Player ID {player_id} cannot raise the bet.")

        # Validate: Bet is physically possible
        if dice_num < 1 or dice_num > self.dice_sides:
            raise ValueError(f"Number on the dice should be between 1 and {self.dice_sides}, inclusive.")
        if dice_count < 1:
            raise ValueError("Dice count must be positive.")

        # Validate: Bet cannot be lowered (mostly)
        if dice_num < self.current_bet[1]:
            raise ValueError("Cannot lower the dice number.")
        if dice_count < self.current_bet[0]:
            if self.allow_count_reset_on_increment:
                # Dice count can be lowered if dice number increases
                if dice_num <= self.current_bet[1]:
                    raise ValueError("Cannot lower the dice count without raising the dice number.")
            else:
                raise ValueError("Cannot lower the dice count.")

        # Validate: Part of the bet has to be raised
        if dice_count == self.current_bet[0] and dice_num == self.current_bet[1]:
            raise ValueError("Bet must be raised.")

        self.current_bet = dice_count, dice_num
        self.caller_idx += 1

    def call_bet(self, player_id: int) -> bool:
        """
        Returns whether bet was true.
        Remember that the bet is if there are AT LEAST X of Y dice on the table.
        """
        if self.current_bet == (0, 0):
            raise RuntimeError("Bet has not been set.")

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
            raise RuntimeError("Not currently in a round.")
        return self.cups[player_id].copy()


if __name__ == "__main__":
    ld = LiarsDiceGame(0, 1, 2)
    print(ld.players)
