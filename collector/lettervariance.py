from __future__ import division
from collector import ItemCollector
from collector.lettercount import ItemLetterCountCollector
from collector.letteraverage import ItemLetterAverageCollector


class LetterVarianceCollector(ItemCollector):

  result_dependencies = (ItemLetterCountCollector,)


  def __init__(self, previous_collector_set):
    ItemCollector.__init__(self, previous_collector_set)
    self.sum_of_squares = 0
    self.letter_average = \
      previous_collector_set[ItemLetterAverageCollector] \
        .get_result(previous_collector_set)


  def collect(self, item, collector_set = None):
    self.sum_of_squares += (len(item) - self.letter_average) ** 2


  def get_result(self, collector_set):
    return self.sum_of_squares / collector_set[ItemLetterCountCollector].get_result()