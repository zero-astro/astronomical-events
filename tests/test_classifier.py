"""Unit tests for classifier module."""

import sys
import os
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from classifier import classify_event


class TestEventClassifier(unittest.TestCase):
    """Test cases for the classify_event function."""

    def test_classify_eclipse(self):
        """Eclipses should be P1 priority."""
        result = classify_event(
            title='Partial Solar Eclipse',
            description_text='A partial solar eclipse visible from Europe.'
        )
        self.assertEqual(result.priority, 1)
        self.assertEqual(result.event_type, 'eclipse')

    def test_classify_meteor_shower_peak(self):
        """Meteor shower peaks should be P2 priority."""
        result = classify_event(
            title='Lyrid meteor shower peak',
            description_text='The annual Lyrid meteor shower reaches its maximum.'
        )
        self.assertEqual(result.priority, 2)
        self.assertEqual(result.event_type, 'meteor_shower')
        self.assertTrue(result.is_meteor_shower_peak)

    def test_classify_comet_perihelion(self):
        """Comet perihelion should be P3 priority (not P1)."""
        result = classify_event(
            title='Comet C/2025 R3 (PANSTARRS) passes perihelion',
            description_text='A bright comet makes its closest approach to the Sun.'
        )
        self.assertEqual(result.priority, 3)
        self.assertEqual(result.event_type, 'comet')

    def test_classify_meteor_shower_non_peak(self):
        """Non-peak meteor showers should be P3 priority."""
        result = classify_event(
            title='Perseid meteor shower begins',
            description_text='The Perseids start this week.'
        )
        self.assertEqual(result.priority, 3)
        self.assertEqual(result.event_type, 'meteor_shower')

    def test_classify_moon_conjunction(self):
        """Moon conjunctions should be P5 priority."""
        result = classify_event(
            title='Moon & Jupiter conjunction',
            description_text='The Moon passes near Jupiter in the evening sky.'
        )
        self.assertEqual(result.priority, 5)
        self.assertEqual(result.event_type, 'moon_conjunction')

    def test_classify_unknown(self):
        """Unknown event types should be P5 priority with type 'unknown'."""
        result = classify_event(
            title='Random astronomical event',
            description_text='An event not matching any known category.'
        )
        self.assertEqual(result.event_type, 'unknown')
        self.assertEqual(result.priority, 5)


if __name__ == '__main__':
    unittest.main()
