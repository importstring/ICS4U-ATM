"""
Curses-based interface for the ATM and live trading application.

Theme manages bank colours and optional colour cycling. TUI draws the
shared layout, menus, input fields, messages, and price graphs.
LoginScreen handles login, registration, and administrator setup.
SimulatorApp connects the interface to authentication, bank storage,
trading, transfers, and the leaderboard.

The screen background is explicitly painted to reduce inconsistent
background colours across terminal configurations.
"""


from __future__ import annotations


import curses
import math
import time


from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


from src.auth import Auth, AuthenticationError, AuthorizationError
from src.records import Admin
from src.simulator import Simulator



class Theme:
    """Manage named bank themes, normal text styling, and optional
    time-based cycling through six accent colours.
    """

    NAMES = {
        "default": 1,
        "england": 2,
        "japan": 3,
        "canada": 4,
        "australia": 5,
        "europe": 6,
    }


    def __init__(self):
        """Select the default theme and initialize colour pairs when
        the terminal supports colours.

        Pairs 1–6 provide accent colours on black backgrounds.
        Pair 7 provides white text on a black background.
        """
        self.name = "default"
        self.animate = False
        self.coloured = curses.has_colors()


        if self.coloured:
            curses.start_color()


            colours = (
                curses.COLOR_CYAN,
                curses.COLOR_BLUE,
                curses.COLOR_MAGENTA,
                curses.COLOR_RED,
                curses.COLOR_YELLOW,
                curses.COLOR_GREEN,
                curses.COLOR_WHITE,
            )


            for pair, foreground in enumerate(colours, start=1):
                curses.init_pair(
                    pair,
                    foreground,
                    curses.COLOR_BLACK,
                )


    def colour(self, pair: int) -> int:
        """Return the drawing attribute for a registered colour pair,
        or zero if the terminal does not support colours.
        """
        return curses.color_pair(pair) if self.coloured else 0


    @property
    def normal(self) -> int:
        """Return the white-on-black style used for normal text."""
        return self.colour(7)


    @property
    def accent(self) -> int:
        """Return the selected theme's accent or a time-cycling accent.

        When animation is enabled, multiplying the monotonic clock by
        three advances approximately three colour steps per second.
        Modulo six wraps the steps, and adding one selects pairs 1–6:
        cyan, blue, magenta, red, yellow, and green.

        Otherwise, use the named theme's pair, falling back to cyan.
        The property is recalculated when accessed; visible animation
        depends on the interface repeatedly redrawing the screen.
        """
        if self.animate:
            pair = int(time.monotonic() * 3) % 6 + 1
        else:
            pair = self.NAMES.get(self.name, 1)


        return self.colour(pair)



class TUI:
    """Provide shared terminal drawing, navigation, text input,
    scrollable messages, and auto-scaled line graphs.

    Drawing methods use a common sidebar and reserve the right-hand
    area for content. Input loops continue refreshing while waiting,
    allowing the selected colour animation to remain visible.
    """

    ART = (
        " ▄▄▄▄▄ ▄▄▄▄▄▄▄  ▄▄▄▄▄▄",
        "░▄▀▀█░ ░▀▀█▀▀░ ░▄▀█▀█░",
        "▒█▄▄█▒   ▒█▒   ▒█▒█▒█▒",
        "▓█▒▓█▓   ▓█▓   ▓█▓▀▓█▓",
        "▀▀▀▀▀▀   ▀▀▀   ▀▀▀ ▀▀▀",
    )


    CONTENT_X = 30
    MIN_WIDTH = 86
    MIN_HEIGHT = 20


    def __init__(self, screen):
        """Configure the curses screen and create its theme.

        Enable special-key input, disable automatic scrolling, and set
        a 50-millisecond input timeout so interface loops can redraw
        without waiting indefinitely for a key.
        """
        self.screen = screen
        self.theme = Theme()
        self.accent = self.theme.accent


        screen.keypad(True)
        screen.scrollok(False)
        screen.timeout(50)
        screen.bkgd(" ", self.theme.normal)


    @property
    def height(self) -> int:
        """Return the terminal screen's current number of rows."""
        return self.screen.getmaxyx()[0]


    @property
    def width(self) -> int:
        """Return the terminal screen's current number of columns."""
        return self.screen.getmaxyx()[1]


    @property
    def ready(self) -> bool:
        """Return whether the screen meets the minimum layout dimensions."""
        return (
            self.height >= self.MIN_HEIGHT
            and self.width >= self.MIN_WIDTH
        )


    def set_theme(self, name: str):
        """Set the theme name used on subsequent screen redraws.

        Unknown names use the default accent when animation is disabled.
        """
        self.theme.name = name


    def toggle_animation(self):
        """Switch time-based accent colour cycling on or off."""
        self.theme.animate = not self.theme.animate


    def put(self, row, column, text, style=None):
        """Draw text at a screen position, clipping it to the available
        width and ignoring positions outside the supported bounds.

        Convert text to a string and use the normal style when no
        explicit style is supplied. Reserve the screen's last column.
        """
        if not (
            0 <= row < self.height
            and 0 <= column < self.width - 1
        ):
            return


        self.screen.addnstr(
            row,
            column,
            str(text),
            self.width - column - 1,
            self.theme.normal if style is None else style,
        )


    def write(self, row, text, selected=False):
        """Draw text at the content area's fixed starting column.

        Use the current frame's bold accent for selected text;
        otherwise, use normal text styling.
        """
        style = (
            self.accent | curses.A_BOLD
            if selected
            else self.theme.normal
        )
        self.put(row, self.CONTENT_X, text, style)


    def frame(self, title, footer=""):
        """Paint the background and draw the shared interface layout.

        Capture one accent style for the frame, explicitly fill blank
        cells, and draw the border, sidebar, artwork, title, and footer.
        Avoid writing directly into the bottom-right cell while filling.

        If the terminal is too small, show a resize message instead
        of the full layout. This method does not refresh the screen.
        """
        self.accent = self.theme.accent
        self.screen.attrset(self.theme.normal)


        # Explicitly colour blank cells, including on light terminals.
        height, width = self.screen.getmaxyx()
        blank_row = " " * width


        for row in range(height):
            count = width - (row == height - 1)


            if count > 0:
                self.screen.addnstr(
                    row, 0, blank_row, count, self.theme.normal
                )


        if not self.ready:
            self.put(
                0,
                0,
                f"Enlarge terminal to at least "
                f"{self.MIN_WIDTH} x {self.MIN_HEIGHT}.",
            )
            return


        self.screen.border()


        for row in range(1, self.height - 1):
            self.put(row, 27, "│", self.accent)


        for row, line in enumerate(self.ART, start=4):
            self.put(
                row, 2, line, self.accent | curses.A_BOLD
            )


        self.put(11, 3, "LIVE TRADING", self.accent)
        self.write(2, title, selected=True)
        self.put(self.height - 2, 2, footer, self.accent)


    def key(self):
        """Refresh the screen, then return a key code or -1 if the
        configured input timeout expires without a key.
        """
        self.screen.refresh()
        return self.screen.getch()


    def menu(self, title, options):
        """Display a scrolling menu and return the selected option index.

        Up and down move with wraparound, Enter selects, and G toggles
        accent animation. Ignore selection input while the terminal
        is smaller than the required dimensions.

        Raises:
            ValueError: If no options are supplied.
        """
        if not options:
            raise ValueError("A menu needs at least one option.")


        selected = 0


        while True:
            self.frame(
                title,
                "↑/↓ Move | Enter Select | G Animate",
            )


            if self.ready:
                count = self.height - 8
                start = max(0, selected - count + 1)
                end = min(len(options), start + count)


                for row, index in enumerate(
                    range(start, end), start=5
                ):
                    prefix = "> " if index == selected else "  "
                    self.write(
                        row,
                        prefix + options[index],
                        selected=index == selected,
                    )


            key = self.key()


            if key in (ord("g"), ord("G")):
                self.toggle_animation()


            if not self.ready:
                continue


            if key == curses.KEY_UP:
                selected = (selected - 1) % len(options)
            elif key == curses.KEY_DOWN:
                selected = (selected + 1) % len(options)
            elif key in (10, 13, curses.KEY_ENTER):
                return selected


    def prompt(self, title, label, secret=False):
        """Collect and return up to 128 printable characters.

        Support Backspace editing and Enter submission. When secret
        is True, display asterisks instead of the entered characters.
        Show only the trailing text when input exceeds the visible width.

        This method collects input but does not validate its meaning.
        """
        text = ""


        while True:
            self.frame(
                title,
                "Enter Submit | Backspace Delete",
            )


            if self.ready:
                self.write(5, label)
                displayed = "*" * len(text) if secret else text
                capacity = max(1, self.width - self.CONTENT_X - 5)
                self.write(7, "> " + displayed[-capacity:])


            self.screen.refresh()


            try:
                key = self.screen.get_wch()
            except curses.error:
                continue


            if not self.ready:
                continue


            if key in ("\n", "\r", curses.KEY_ENTER):
                return text
            elif key in ("\b", "\x7f", curses.KEY_BACKSPACE):
                text = text[:-1]
            elif isinstance(key, str) and key.isprintable():
                if len(text) < 128:
                    text += key


    def message(self, title, text):
        """Display a scrollable text message until Enter or Escape.

        Up and down scroll through lines. Long lines are clipped by
        the drawing method rather than wrapped. Existing animation
        continues, but this screen does not handle the G toggle.
        """
        lines = str(text).splitlines()
        offset = 0


        while True:
            self.frame(
                title,
                "↑/↓ Scroll | Enter/Esc Back",
            )


            if self.ready:
                count = self.height - 8
                maximum_offset = max(0, len(lines) - count)
                offset = min(offset, maximum_offset)


                for row, line in enumerate(
                    lines[offset:offset + count], start=5
                ):
                    self.write(row, line)


            key = self.key()


            if not self.ready:
                continue


            if key == curses.KEY_UP:
                offset = max(0, offset - 1)
            elif key == curses.KEY_DOWN:
                offset = min(maximum_offset, offset + 1)
            elif key in (10, 13, curses.KEY_ENTER, 27):
                return


    def draw_line(
        self,
        values,
        labels,
        y_label="Price (CAD)",
    ):
        """Draw an auto-scaled line graph inside the current frame.

        Map equally spaced observations to terminal columns, connect
        adjacent points with ASCII characters, and mark samples with
        asterisks. Draw price ticks, horizontal guides, and up to three
        x-axis labels.

        Add padding around the value range and provide a nonzero range
        for constant data. Increase y-axis decimal precision when needed
        to distinguish tick labels. Do not force nonnegative data to
        have a zero baseline.

        Args:
            values: Finite numeric observations in time order.
            labels: Matching x-axis labels for the observations.
            y_label: Description of the y-axis and its units.

        Raises:
            ValueError: If chart data is empty, mismatched, nonfinite,
                or cannot be converted to floats.

        Return without drawing if the terminal is too small.
        """
        if not self.ready:
            return


        values = [float(value) for value in values]


        if not values or len(values) != len(labels):
            raise ValueError(
                "Provide matching, nonempty chart data."
            )


        if any(not math.isfinite(value) for value in values):
            raise ValueError("Chart values must be finite.")


        minimum, maximum = min(values), max(values)
        padding = (
            (maximum - minimum) * 0.1
            or max(abs(minimum) * 0.05, 0.000001)
        )


        low = minimum - padding
        high = maximum + padding


        if minimum >= 0:
            low = max(0, low)


        top = 7
        rows = self.height - 13


        tick_rows = sorted({
            round(index * (rows - 1) / 4)
            for index in range(5)
        })


        ticks = [
            high - row / (rows - 1) * (high - low)
            for row in tick_rows
        ]


        precision = 2


        while precision < 12:
            tick_labels = [
                f"{value:.{precision}f}"
                for value in ticks
            ]


            if len(set(tick_labels)) == len(tick_labels):
                break


            precision += 1


        tick_labels = [
            f"{value:.{precision}f}"
            for value in ticks
        ]


        label_width = max(map(len, tick_labels))
        axis_x = self.CONTENT_X + label_width + 1
        plot_x = axis_x + 1
        columns = self.width - plot_x - 2


        if columns < 8:
            self.write(7, "Enlarge terminal to fit graph.")
            return


        self.write(6, y_label)


        grid = [[" "] * columns for _ in range(rows)]


        for row in tick_rows:
            grid[row] = ["."] * columns


        points = []


        for index, value in enumerate(values):
            x = (
                columns // 2
                if len(values) == 1
                else round(
                    index / (len(values) - 1) * (columns - 1)
                )
            )
            y = round(
                (high - value) / (high - low) * (rows - 1)
            )


            points.append((x, max(0, min(rows - 1, y))))


        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            dx, dy = x2 - x1, y2 - y1
            steps = max(abs(dx), abs(dy), 1)


            character = (
                "|" if dx == 0
                else "-" if dy == 0
                else "/" if dy < 0
                else "\\"
            )


            for step in range(steps + 1):
                x = round(x1 + dx * step / steps)
                y = round(y1 + dy * step / steps)
                grid[y][x] = character


        for x, y in points:
            grid[y][x] = "*"


        for row, line in enumerate(grid):
            self.put(top + row, axis_x, "|", self.accent)
            self.put(
                top + row,
                plot_x,
                "".join(line),
                self.accent,
            )


        for row, label in zip(tick_rows, tick_labels):
            self.put(
                top + row,
                self.CONTENT_X,
                label.rjust(label_width),
            )


        bottom = top + rows
        self.put(
            bottom,
            axis_x,
            "+" + "-" * columns,
            self.accent,
        )


        previous_end = -1


        for index in sorted({
            0,
            (len(labels) - 1) // 2,
            len(labels) - 1,
        }):
            label = str(labels[index])[
                :max(1, columns // 3 - 1)
            ]
            start = max(
                0,
                min(
                    columns - len(label),
                    points[index][0] - len(label) // 2,
                ),
            )


            if start > previous_end:
                self.put(bottom + 1, plot_x + start, label)
                previous_end = start + len(label)


        self.put(bottom + 2, plot_x, "Time (market ticks)")



class LoginScreen:
    """Collect credentials and navigate administrator setup, customer
    registration, and login through the Auth service.
    """

    def __init__(self, ui: TUI, auth: Auth):
        """Store the shared interface and authentication service."""
        self.ui = ui
        self.auth = auth


    def password(self, title):
        """Collect a masked password and confirmation, returning the
        password if both entries match.

        Password-length and content rules are enforced later by Auth.

        Raises:
            ValueError: If the two entries do not match.
        """
        password = self.ui.prompt(
            title,
            "Password (8–128 characters):",
            secret=True,
        )
        confirmation = self.ui.prompt(
            title,
            "Confirm password:",
            secret=True,
        )


        if password != confirmation:
            raise ValueError("Passwords do not match.")


        return password


    def setup(self):
        """Offer Simon's password setup while no administrator exists.

        Display handled validation or authorization errors and allow
        another attempt.

        Returns:
            bool: True when administrator setup is complete, or False
                if the user chooses to exit.
        """
        while self.auth.needs_admin_setup:
            choice = self.ui.menu(
                "Administrator setup",
                ["Set Simon's password", "Exit"],
            )


            if choice == 1:
                return False


            try:
                self.auth.setup_admin(self.password("Simon"))
            except (ValueError, AuthorizationError) as error:
                self.ui.message("Setup failed", error)


        return True


    def enter(self, register=False):
        """Collect credentials and log in, optionally registering a new
        customer identity before authentication.

        Returns:
            str | None: The authenticated session token, or None after
                displaying a handled registration or login error.
        """
        title = "Register" if register else "Log in"
        username = self.ui.prompt(title, "Username:")


        try:
            if register:
                password = self.password(title)
                self.auth.register(username, password)
            else:
                password = self.ui.prompt(
                    title, "Password:", secret=True
                )


            return self.auth.login(username, password)


        except (
            ValueError,
            AuthenticationError,
            AuthorizationError,
        ) as error:
            self.ui.message("Authentication failed", error)
            return None



class SimulatorApp:
    """Coordinate authenticated navigation, bank accounts, live trading,
    transfers, administrator actions, and leaderboard display.

    Delegate identity and permission checks to Auth and financial
    operations to Simulator. Save bank-record changes through BankStore.
    """

    ORDER_SIZES = (1, 5, 10, 25, 50, 100)
    TICK_INTERVAL = 0.75


    def __init__(self, ui, simulator: Simulator, auth, bank_store):
        """Store the application's shared services and create its
        login-screen controller.
        """
        self.ui = ui
        self.simulator = simulator
        self.auth = auth
        self.bank_store = bank_store
        self.login = LoginScreen(ui, auth)


    def show_leaderboard(self, token):
        """Display ranked total equity in CAD and individual score details.

        Obtain calculated and sorted rows from Simulator.leaderboard(),
        mark the current individual, and allow manual refresh or return.
        Sorting is performed by the simulator, not by this screen.

        Show an explanatory message when no funded individuals appear.
        """
        while True:
            rows = self.simulator.leaderboard(token)


            if not rows:
                self.ui.message(
                    "Leaderboard",
                    "No funded trading accounts yet.\n\n"
                    "Open and unlock a bank account to join.",
                )
                return


            current_id = str(
                self.auth.current_user(token).id
            )


            options = []


            for row in rows:
                marker = " [you]" if row["user_id"] == current_id else ""


                options.append(
                    f"#{row['rank']} {row['username']}{marker}"
                    f" | CAD {row['equity']:,.2f}"
                    f" | {row['return_percent']:+.2f}%"
                )


            choice = self.ui.menu(
                "Leaderboard | Total equity in CAD",
                options + ["Refresh", "Back"],
            )


            if choice == len(rows) + 1:
                return


            if choice == len(rows):
                continue


            row = rows[choice]


            self.ui.message(
                f"#{row['rank']} | {row['username']}",
                f"Total equity: CAD {row['equity']:,.2f}\n"
                f"Cash: CAD {row['cash']:,.2f}\n"
                f"Stocks: CAD {row['stocks']:,.2f}\n\n"
                f"Starting credit: CAD 10,000.00\n"
                f"Profit / loss: CAD {row['profit']:+,.2f}\n"
                f"Return: {row['return_percent']:+.2f}%",
            )


    def save_banks(self):
        """Save all registered banks and their current accounts through
        the configured bank store.
        """
        self.bank_store.save(Admin.get_banks())


    def choose(self, title, items, label=str):
        """Display a selection menu for an iterable of objects.

        Use label to produce each object's display text and append a
        Back option. Display a message if the iterable is empty.

        Returns:
            object | None: The selected object, or None if no items
                are available or the user chooses Back.
        """
        items = list(items)


        if not items:
            self.ui.message(title, "Nothing available.")
            return None


        choice = self.ui.menu(
            title,
            [label(item) for item in items] + ["Back"],
        )


        return None if choice == len(items) else items[choice]


    def run(self):
        """Complete administrator setup and run the welcome menu.

        Allow login, registration, or exit. For each successful login,
        run the individual's session and always log out and restore
        the default theme when that session ends or raises an error.
        """
        if not self.login.setup():
            return


        while True:
            choice = self.ui.menu(
                "Welcome",
                ["Log in", "Register", "Exit"],
            )


            if choice == 2:
                return


            token = self.login.enter(register=choice == 1)


            if token:
                try:
                    self.session(token)
                finally:
                    self.auth.logout(token)
                    self.ui.set_theme("default")


    def session(self, token):
        """Run the authenticated individual's main navigation loop.

        Offer account access, account creation, bank information,
        leaderboard viewing, password changes, and logout. Include
        administrator navigation only for an administrator identity.

        Display handled validation and permission errors. Return after
        logout or a successful password change, which ends the sessions.
        """
        while True:
            user = self.auth.current_user(token)


            options = [
                "My bank accounts",
                "Open bank account",
                "Banks",
                "Leaderboard",
            ]


            if user.is_admin:
                options.append("Administrator")


            options += ["Change password", "Log out"]


            action = options[
                self.ui.menu(f"Welcome, {user.username}", options)
            ]


            try:
                if action == "Log out":
                    return


                elif action == "My bank accounts":
                    self.accounts(token)


                elif action == "Leaderboard":
                    self.show_leaderboard(token)


                elif action == "Open bank account":
                    self.open_account(token)


                elif action == "Banks":
                    bank = self.choose_bank(token)
                    if bank:
                        self.bank_info(bank)


                elif action == "Administrator":
                    self.admin(token)


                elif action == "Change password":
                    current = self.ui.prompt(
                        "Password",
                        "Current password:",
                        secret=True,
                    )


                    self.auth.change_password(
                        token,
                        current,
                        self.login.password("New password"),
                    )


                    self.ui.message(
                        "Password changed",
                        "Please log in again.",
                    )
                    return


            except (
                ValueError,
                AuthenticationError,
                AuthorizationError,
            ) as error:
                self.ui.message("Action failed", error)


    def choose_bank(self, token):
        """Return a selected registered bank after session verification,
        or None if no bank is available or Back is selected.
        """
        return self.choose(
            "Choose bank",
            self.auth.get_banks(token),
            lambda bank: f"{bank.name} | {bank.currency}",
        )


    def bank_info(self, bank):
        """Display a bank's currency, named advantage, base trading fee,
        and cross-currency transfer fee.

        State that same-currency transfers do not incur a transfer fee.
        """
        terms = self.simulator.terms(bank.currency)


        self.ui.message(
            bank.name,
            f"Currency: {bank.currency}\n"
            f"Advantage: {terms.name}\n"
            f"Base trading fee: {terms.trade_rate * 100:.2f}%\n"
            f"Currency-transfer fee: {terms.fx_rate * 100:.2f}%\n"
            "Same-currency transfers: no fee",
        )


    def open_account(self, token):
        """Collect a bank, account type, and confirmed account password.

        Create the account for the authenticated individual, save bank
        records, and display its ID. Return without creating an account
        if bank or account-type selection is cancelled.
        """
        bank = self.choose_bank(token)


        if not bank:
            return


        self.bank_info(bank)


        kind = self.choose(
            "Account type",
            list(bank.ACCOUNT_TYPES),
        )


        if not kind:
            return


        account = self.auth.create_account(
            token,
            bank.id,
            kind,
            self.login.password("Account password"),
        )


        self.save_banks()


        self.ui.message(
            "Account opened",
            f"{bank.name}\n{account.id}\n\n"
            "Open it from 'My bank accounts' to begin.",
        )


    def accounts(self, token):
        """Select and unlock one of the authenticated individual's
        bank accounts, then display its account menu.

        Initialize trading data if needed and apply the bank's theme.
        Offer live trading, balance and holdings summaries, transfers,
        and bank information.

        Lock the account and restore the previous theme when leaving
        the account flow, including when an error occurs.
        """
        banks = {
            bank.id: bank
            for bank in self.auth.get_banks(token)
        }


        account = self.choose(
            "My bank accounts",
            self.auth.get_my_accounts(token),
            lambda item: (
                f"{banks[item.bank_id].name}"
                f" | {item.acc_type}"
                f" | {str(item.id)[:8]}"
            ),
        )


        if not account:
            return


        bank = banks[account.bank_id]
        previous_theme = self.ui.theme.name


        try:
            password = self.ui.prompt(
                bank.name,
                "Account password:",
                secret=True,
            )


            self.auth.unlock_account(
                token,
                bank.id,
                account.id,
                password,
            )


            self.simulator.ensure_account(
                token, bank, account
            )


            self.ui.set_theme(bank.theme)


            while True:
                choice = self.ui.menu(
                    f"{bank.name} | {account.acc_type}",
                    [
                        "Live trading",
                        "Cash and holdings",
                        "Transfer cash",
                        "Bank advantages",
                        "Back",
                    ],
                )


                if choice == 0:
                    self.live_trading(token, bank, account)
                elif choice == 1:
                    self.summary(token, bank, account)
                elif choice == 2:
                    self.transfer(token, bank, account)
                elif choice == 3:
                    self.bank_info(bank)
                else:
                    return


        finally:
            self.auth.lock_account(token, account.id)
            self.ui.set_theme(previous_theme)


    def summary(self, token, bank, account):
        """Display an accessible account's cash, total equity in its
        bank currency, and share quantities for each holding.
        """
        entry = self.simulator.account(
            token, bank, account
        )


        equity = self.simulator.equity(
            token, bank, account
        )


        lines = [
            f"Cash: {Decimal(entry['cash']):,.2f} {bank.currency}",
            f"Equity: {equity:,.2f} {bank.currency}",
            "",
        ]


        holdings = [
            f"{symbol}: {quantity} shares"
            for symbol, quantity in entry["holdings"].items()
        ]


        lines.extend(holdings or ["No shares owned."])


        self.ui.message(
            "Cash and holdings",
            "\n".join(lines),
        )


    def transfer(self, token, bank, account):
        """Collect and confirm a cash transfer to another account owned
        by the authenticated individual.

        Require the destination account's password and initialize its
        trading entry if needed. Validate a finite, positive source
        amount up to one trillion, round it to cents, and preview the
        debit, conversion, and fee before confirmation.

        Delegate the saved balance changes to Simulator.transfer().
        Always lock the destination account when leaving this flow.

        Raises:
            ValueError: If the entered amount or transfer is invalid.
        """
        banks = {
            item.id: item
            for item in self.auth.get_banks(token)
        }


        targets = [
            item
            for item in self.auth.get_my_accounts(token)
            if item.id != account.id
        ]


        target = self.choose(
            "Transfer to",
            targets,
            lambda item: (
                f"{banks[item.bank_id].name}"
                f" | {item.acc_type}"
                f" | {str(item.id)[:8]}"
            ),
        )


        if not target:
            return


        target_bank = banks[target.bank_id]


        try:
            password = self.ui.prompt(
                target_bank.name,
                "Destination account password:",
                secret=True,
            )


            self.auth.unlock_account(
                token,
                target_bank.id,
                target.id,
                password,
            )


            self.simulator.ensure_account(
                token, target_bank, target
            )


            raw = self.ui.prompt(
                "Transfer cash",
                f"Amount in {bank.currency}:",
            )


            try:
                amount = Decimal(raw.strip())


                if (
                    not amount.is_finite()
                    or not 0 < amount <= Decimal("1e12")
                ):
                    raise ValueError


                amount = amount.quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )


                if amount <= 0:
                    raise ValueError


            except (InvalidOperation, ValueError):
                raise ValueError(
                    "Enter a positive amount up to 1 trillion."
                ) from None


            rate = self.simulator.rate(
                bank.currency,
                target_bank.currency,
            )


            fee_rate = self.simulator.terms(
                bank.currency
            ).fx_rate


            fee = (
                (amount * fee_rate).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
                if bank.currency != target_bank.currency
                else Decimal("0")
            )


            credited = (amount * rate).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )


            choice = self.ui.menu(
                f"Debit {amount + fee:,.2f} {bank.currency}",
                [
                    f"Confirm | credit {credited:,.2f}"
                    f" {target_bank.currency} | fee {fee:,.2f}",
                    "Cancel",
                ],
            )


            if choice != 0:
                return


            credited, fee = self.simulator.transfer(
                token,
                bank,
                account,
                target_bank,
                target,
                amount,
            )


            self.ui.message(
                "Transfer saved",
                f"Received: {credited:,.2f} {target_bank.currency}\n"
                f"Fee: {fee:,.2f} {bank.currency}",
            )


        finally:
            self.auth.lock_account(token, target.id)


    def live_trading(self, token, bank, account):
        """Run live account-based trading until the user presses Q.

        Advance and save one market step when each scheduled tick is
        reached, redraw the selected asset's price graph, and display
        cash, equity, holdings, order size, and the applicable fee.

        Left and right switch assets, up and down change order size,
        B buys, S sells, and G toggles colour animation. Orders settle
        through the unlocked account and are saved by the simulator.

        Continue market updates while the terminal is too small, but
        ignore trading controls until the layout is usable again.
        There is no round timer or portfolio reset.
        """
        asset_index = 0
        size_index = 2
        status = "B buys | S sells | Orders save immediately"
        next_tick = time.monotonic() + self.TICK_INTERVAL


        while True:
            self.auth.require_account_access(
                token, bank.id, account.id
            )


            if time.monotonic() >= next_tick:
                self.simulator.advance()
                next_tick = (
                    time.monotonic() + self.TICK_INTERVAL
                )


            assets = self.simulator.assets()


            if not assets:
                self.ui.message(
                    "Trading unavailable",
                    "No assets are available.",
                )
                return


            asset_index %= len(assets)
            asset = assets[asset_index]
            quantity = self.ORDER_SIZES[size_index]


            entry = self.simulator.account(
                token, bank, account
            )


            fee_rate = self.simulator.terms(
                bank.currency
            ).rate_for(asset.currency)


            # Convert the displayed order into account currency.
            gross = (
                asset.price
                * quantity
                * self.simulator.rate(
                    asset.currency,
                    bank.currency,
                )
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )


            fee = (gross * fee_rate).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )


            self.ui.frame(
                f"{asset.symbol} {asset.price:,.2f}"
                f" {asset.currency} | Tick {self.simulator.step}",
                "B Buy | S Sell | ←/→ Stock | ↑/↓ Size | G Colour | Q Back",
            )


            if self.ui.ready:
                equity = self.simulator.equity(
                    token, bank, account
                )


                self.ui.write(
                    3,
                    f"Cash {Decimal(entry['cash']):,.2f}"
                    f" | Equity {equity:,.2f} {bank.currency}",
                )


                self.ui.write(
                    4,
                    f"Owned {entry['holdings'].get(asset.symbol, 0)}"
                    f" | Size {quantity}"
                    f" | Buy total {gross + fee:,.2f} {bank.currency}"
                    f" | Fee {fee_rate * 100:.2f}%",
                )


                self.ui.write(5, status)


                self.ui.draw_line(
                    asset.history,
                    [
                        str(
                            self.simulator.step
                            - len(asset.history)
                            + 1
                            + index
                        )
                        for index in range(len(asset.history))
                    ],
                    y_label=f"Price ({asset.currency})",
                )


            key = self.ui.key()


            if key in (ord("q"), ord("Q")):
                return


            if key in (ord("g"), ord("G")):
                self.ui.toggle_animation()


            if not self.ui.ready:
                continue


            if key == curses.KEY_LEFT:
                asset_index = (
                    asset_index - 1
                ) % len(assets)


            elif key == curses.KEY_RIGHT:
                asset_index = (
                    asset_index + 1
                ) % len(assets)


            elif key == curses.KEY_UP:
                size_index = min(
                    len(self.ORDER_SIZES) - 1,
                    size_index + 1,
                )


            elif key == curses.KEY_DOWN:
                size_index = max(0, size_index - 1)


            elif key in (
                ord("b"), ord("B"), ord("s"), ord("S")
            ):
                side = (
                    "BUY"
                    if key in (ord("b"), ord("B"))
                    else "SELL"
                )


                try:
                    event = self.simulator.trade(
                        token,
                        bank,
                        account,
                        side,
                        asset.symbol,
                        quantity,
                    )


                    status = (
                        f"{side} {quantity} {asset.symbol}"
                        f" | Fee {event['fee']}"
                        f" {bank.currency} | Saved"
                    )


                except ValueError as error:
                    status = str(error)


    def admin(self, token):
        """Run the administrator menu after checking administrator access.

        Display system counts, create banks with selected currencies and
        themes, or remove banks and individual bank accounts after
        confirmation. Save bank records after each completed mutation.

        Removal does not liquidate or transfer funds or stocks; the
        confirmation warns that those holdings become inaccessible.
        """
        self.auth.require_admin(token)


        while True:
            choice = self.ui.menu(
                "Administrator",
                [
                    "Overview",
                    "Create bank",
                    "Remove bank",
                    "Remove account",
                    "Back",
                ],
            )


            if choice == 4:
                return


            if choice == 0:
                info = self.auth.get_admin_info(token)


                self.ui.message(
                    "Overview",
                    "\n".join(
                        f"{key.replace('_', ' ')}: {value}"
                        for key, value in info.items()
                    ),
                )


            elif choice == 1:
                name = self.ui.prompt(
                    "Create bank", "Name:"
                )


                currency = self.choose(
                    "Currency and advantages",
                    self.simulator.currencies,
                )


                if not currency:
                    continue


                theme = self.choose(
                    "Theme", list(Theme.NAMES)
                )


                if theme:
                    self.auth.create_bank(
                        token, name, currency, theme
                    )
                    self.save_banks()


            else:
                bank = self.choose_bank(token)


                if not bank:
                    continue


                if choice == 2:
                    confirmation = self.ui.menu(
                        f"Remove {bank.name}?",
                        [
                            "Cancel",
                            "Remove bank; its funds/stocks become inaccessible",
                        ],
                    )


                    if confirmation == 1:
                        self.auth.remove_bank(
                            token, bank.id
                        )
                        self.save_banks()


                else:
                    self.auth.require_admin(token)


                    account = self.choose(
                        "Remove account",
                        list(bank.accounts.values()),
                        lambda item: (
                            f"{item.acc_type} | {item.id}"
                        ),
                    )


                    if not account:
                        continue


                    confirmation = self.ui.menu(
                        "Remove account?",
                        [
                            "Cancel",
                            "Remove; its funds/stocks become inaccessible",
                        ],
                    )


                    if confirmation == 1:
                        self.auth.remove_account(
                            token,
                            bank.id,
                            account.id,
                        )
                        self.save_banks()