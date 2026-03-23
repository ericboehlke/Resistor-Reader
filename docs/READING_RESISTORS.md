# How to read resistors

Wherever we see strings of colors, these should be replaced with a ColorsEnum type.

The first two resistor bands denote significant figures in the resistance value.
They are mapped by the following from colors to numbers.

```python
DIGIT_MAP = {
    "black": 0,
    "brown": 1,
    "red": 2,
    "orange": 3,
    "yellow": 4,
    "green": 5,
    "blue": 6,
    "violet": 7,
    "grey": 8,
    "gray": 8,
    "white": 9,
}
```

The third band denotes the multiplier to give the order of magnitude of the resistance.
The following maps the third band.

```python
MULTIPLIER_MAP = {
    "black": 1,
    "brown": 10,
    "red": 100,
    "orange": 1_000,
    "yellow": 10_000,
    "green": 100_000,
    "blue": 1_000_000,
    "violet": 10_000_000,
    "grey": 100_000_000,
    "gray": 100_000_000,
    "white": 1_000_000_000,
    "gold": 0.1,
    "silver": 0.01,
}
```

The last band is tolerance and doesn't matter for our purposes. 
It will likely always be gold.
