### Day 1: Tue Oct 06th 2026

Decided to go with dataclasses. Really nice formatting touch and since lists are off the table, great time to practise some good formatting practises. To learn it I made this example

```python
from dataclasses import dataclass

@dataclass
class Person:
name: str
age: int
hobbies: set = ("doomscrolling")
city: str = "unknown"

Simon = Person(
name="Simon", age=17, city="Toronto", hobbies="guitar"
)

print(Simon.name)
print(Simon.hobbies)
```

Messed around with it a bit so that if I don't enter a hobbie it prints doomscrolling, a slightly offensive jab at a user without any hobbies and a feature to set location to unknown if they don't enter anything.

### Day 2: Thu Oct 22nd 2026

Some experiements with cureses. I want to get more comfortable so I'm stopping copying and pasting from docs and instead I want to be able to write by hand. Did some time with this.

```python
import curses


def draw_text(stdscr, y, x, text, attr=0):
    rows, cols = stdscr.getmaxyx()

    # Leave the final column empty to avoid bottom-right write errors.
    if 0 <= y < rows and 0 <= x < cols - 1:
        stdscr.addnstr(y, x, text, cols - x - 1, attr)


def main(stdscr):
    stdscr.keypad(True)
    y, x = 5, 5
    label = "Move me!"

    while True:
        rows, cols = stdscr.getmaxyx()

        # Keep the label inside the window, including after resizing.
        y = max(0, min(y, rows - 1))
        x = max(0, min(x, cols - len(label) - 1))

        stdscr.erase()
        draw_text(stdscr, y, x, label)
        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP:
            y -= 1
        elif key == curses.KEY_DOWN:
            y += 1
        elif key == curses.KEY_LEFT:
            x -= 1
        elif key == curses.KEY_RIGHT:
            x += 1
        elif key == ord("q"):
            break


def menu(stdscr):
    stdscr.keypad(True)
    options = ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"]
    selected = 0

    while True:
        stdscr.erase()

        for i, option in enumerate(options):
            attr = curses.A_REVERSE if i == selected else curses.A_NORMAL
            draw_text(stdscr, i + 1, 2, option, attr)

        stdscr.refresh()
        key = stdscr.getch()

        if key in (curses.KEY_UP, curses.KEY_LEFT):
            selected = (selected - 1) % len(options)
        elif key in (curses.KEY_DOWN, curses.KEY_RIGHT):
            selected = (selected + 1) % len(options)
        elif key in (curses.KEY_ENTER, 10, 13):
            return options[selected]
        elif key == ord("q"):
            return None


if __name__ == "__main__":
    curses.wrapper(main)
    choice = curses.wrapper(menu)

    if choice is not None:
        print(choice)
```
