## ATM & Live Trading App

![Demo](demo.gif)

### Key:

[X] completely address [E] eliminated [-] Not completed
[=] somewhat completely

Criteria:
[X] Save user records --> done in classes in `src/records`
[E] Add two or more attributes of your choice: stock holdings
[X] Require unique password and username --> `auth.py`
[X] Add built in accounts - Admin: Simon pass: 12345678 - Other player accounts from family members - 3+ for sure
[E] Include an algorithm that calculates the average - I thought a leaderboard would be better.
Challenges:
[E] Build an interest rate projector - Live stock trading
[=] Build three searching algorithms - Built insertion sort - Wide range of array manipulation
[E] Keep a record of transactions with time stamps - Detailed stock logs and trading logs
[X] Allow the user to transfer funds from one account to another
[X] Include a currency converter

    ________
    |  ATM   |
    |        |   Menu
    |        |  1
    |        |  2
    |        |  3
    ________

    ^ Design inspo

Live trading is done with ascii characters

| ._._. ./
| ./ \.\_./
|\_\_.
b for buy, s for sell, up and down adjust buy increments, side arrows shift through graphs.

Storage is done in `data/` and the code for it is done in `src/storage.py`

The admin (Simon) can create & delete banks. The UI is done in `src/ui.py`

ATM ascii art was found here: https://patorjk.com/software/taag/#p=display&f=File+Blue&t=Hello+User&x=none&v=4&h=4&w=80&we=false&ft=thedraw
Some code for graphs and for curses menu was taken off of the internet.

Used the python built in library `uuid` to generate unique IDs that are more secure.
Also used the ClassVar and Mapping library from typing to allow me to create this class that allows me to have the class `Admin` almost function as an instance. I liked how this looked:

```python
admin.remove_bank("Bank of Canada")
```

As for records, I probably rewrote this file 10 or 20 times. I decided to go with using a lot of dataclasses.

Then for `src/simulator.py`, I created some new classes like an `Asset` dataclass and one for BankTerms. I decided to put this in simulator instead of records because I thought they were more related to trading.

On line 220 you can find an insertion sort implementation that's used for the trading leaderboard.

#### Logins

Simon (admin) — 12345678
