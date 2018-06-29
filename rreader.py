import numpy
import PIL.Image


def threshold_red(rgb):
    r, g, b = rgb
    return r > 1.5 * g and r > 2 * b


def rread(array):
    """
    Take a numpy array of the picture of a resistor and return the
    value of the resistor in ohms
    :param array: numpy array of picture of resistor
    :return: value of resistor in ohms
    """
    return 100


if __name__ == '__main__':
    rread(numpy.asarray(PIL.Image.open('resistors/0001.jpg')))
