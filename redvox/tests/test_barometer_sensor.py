import redvox.api900.reader as reader
import redvox.api900.exceptions as exceptions
from redvox.tests.utils import *

import unittest

from numpy import array, array_equal


class TestBarometerSensor(unittest.TestCase):
    def setUp(self):
        self.example_sensor = reader.read_rdvxz_file(test_data("example.rdvxz")).barometer_channel()
        self.empty_sensor = reader.BarometerSensor()

    def test_get_payload_values(self):
        self.assertTrue(array_equal([-10.0, 0.0, 10.0, 20.0, 15.0, -6.0, 0.0], self.example_sensor.payload_values()))
        self.assertTrue(array_equal([], self.empty_sensor.payload_values()))

    def test_set_payload_values(self):
        self.example_sensor.set_payload_values([1.0, 2.0, 3.0])
        self.empty_sensor.set_payload_values(array([1.0, 2.0, 3.0]))
        self.assertTrue(array_equal([1.0, 2.0, 3.0], self.example_sensor.payload_values()))
        self.assertTrue(array_equal([1.0, 2.0, 3.0], self.empty_sensor.payload_values()))

    def test_get_payload_mean(self):
        self.assertAlmostEqual(4.1428571428571, self.example_sensor.payload_mean())

        with self.assertRaises(exceptions.ReaderException):
            self.assertAlmostEqual(4.1428571428571, self.empty_sensor.payload_mean())

    def test_get_payload_median(self):
        self.assertAlmostEqual(0.0, self.example_sensor.payload_median())

        with self.assertRaises(exceptions.ReaderException):
            self.assertAlmostEqual(4.1428571428571, self.empty_sensor.payload_median())

    def test_get_payload_std(self):
        self.assertAlmostEqual(10.28769822, self.example_sensor.payload_std())

        with self.assertRaises(exceptions.ReaderException):
            self.assertAlmostEqual(4.1428571428571, self.empty_sensor.payload_std())



