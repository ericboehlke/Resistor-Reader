import csv
import numpy
import rreader
import PIL.Image


class TestResistors:
    def test_resistors(self):
        with open('resistor_pictures/resistors.csv', 'r') as csvfile:
            reader = csv.reader(csvfile, delimiter=',', quotechar='|')
            for number, value in reader:
                yield self.check_resistors, 'resistor_pictures/'+str(number).zfill(4)+'.jpg', int(value)

    @staticmethod
    def check_resistors(fname, value):
        assert rreader.rread(numpy.asarray(PIL.Image.open(fname))) == value


if __name__ == "__main__":
    test = TestResistors()
    for i in test.test_resistors():
        pass
