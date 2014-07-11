from __future__ import absolute_import, division
import utilities.string
from utilities.pdb import ProbabilityDistribution
from . import ItemCollector
from .lettercount import ItemLetterCountCollector
from .absoluteletterfrequency import ItemLetterAbsoluteFrequencyCollector


class ItemLetterRelativeFrequencyCollector(ItemCollector):

  result_dependencies = (ItemLetterAbsoluteFrequencyCollector,)


  def __init__(self, previous_collector_set):
    ItemCollector.__init__(self, previous_collector_set)
    self.letter_count = previous_collector_set[ItemLetterCountCollector].get_result()


  def get_result(self, collector_set):
    return ((char, frequency / self.letter_count)
      for char, frequency in
        collector_set[ItemLetterAbsoluteFrequencyCollector].get_result(collector_set).iteritems())


  def as_str(self, collector_set, number_fmt=''):
    return u'({})'.format(u', '.join((
      u'{}: {:{}}'.format(utilities.string.char_repr(char), frequency, number_fmt)
      for char, frequency in self.get_result(collector_set))))


  @staticmethod
  def result_norm(a, b):
    return ProbabilityDistribution(a).distance_to(ProbabilityDistribution(b)) * 0.5
