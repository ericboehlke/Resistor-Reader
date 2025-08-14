# Resistor-Reader

A project to read the color code on resistors.

## Development

This project uses [uv](https://github.com/astral-sh/uv) for dependency
management and [flit](https://flit.pypa.io) as the build backend.

Install the dependencies:

```bash
uv sync
```

Run the tests:

```bash
uv run pytest
```

Build a distribution:

```bash
uv build
```

## Building an Image

A Yocto meta-layer is provided in `yocto/` for producing a minimal Raspberry Pi
Zero image with the project and its dependencies preinstalled. See
[`yocto/README.md`](yocto/README.md) for detailed instructions.
