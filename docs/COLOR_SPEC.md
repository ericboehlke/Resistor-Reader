# Approximate Color References

The following are reference RGB values that are somewhat accurate for the lighting we can expect from the camera.
These values are provided in RGB but we will likely use LAB or HSV color spaces in the application.

```python
COLOR_RGB: Dict[str, Tuple[int, int, int]] = {
    "black": (0.193 * 255, 0.121 * 255, 0.092 * 255),
    "brown": (0.421 * 255, 0.163 * 255, 0.130 * 255),
    "red": (0.479 * 255, 0.114 * 255, 0.113 * 255),
    "orange": (0.583 * 255, 0.235 * 255, 0.121 * 255),
    "yellow": (0.485 * 255, 0.345 * 255, 0.093 * 255),
    "green": (0.085 * 255, 0.170 * 255, 0.169 * 255),
    "blue": (0.084 * 255, 0.146 * 255, 0.216 * 255),
    "violet": (0.199 * 255, 0.163 * 255, 0.267 * 255),
    "gray": (0.379 * 255, 0.305 * 255, 0.281 * 255),
    "white": (0.510 * 255, 0.403 * 255, 0.356 * 255),
    "gold": (0.472 * 255, 0.251 * 255, 0.154 * 255),
    "silver": (192, 192, 192),
}

# Pre-compute LAB references for classification
_REF_LAB = {
    name: cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0]
    for name, rgb in COLOR_RGB.items()
}
```
