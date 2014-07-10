#!/usr/bin/python
from __future__ import print_function
import csv, sys, os.path, itertools, operator, math, locale
import collector, collector.columntype
import utilities
from utilities import (infinity, DecodableUnicode)
import utilities.iterator as uiterator
import utilities.functional as ufunctional
import utilities.operator as uoperator
from collector import MultiphaseCollector
from collector.columntype import ColumnTypeItemCollector
from collector.itemaverage import ItemAverageCollector
from collector.letteraverage import ItemLetterAverageCollector
from collector.variance import ItemStandardDeviationCollector
from collector.lettervariance import LetterStandardDeviationCollector
from collector.relativeletterfrequency import ItemLetterRelativeFrequencyCollector


number_format = '10.4e'

# TODO: tweak
collector_phase_description = (
  (collector.columntype.factory(
    ItemLetterAverageCollector, ItemAverageCollector),
  ),
  (collector.columntype.factory(
    LetterStandardDeviationCollector, ItemStandardDeviationCollector),
  collector.columntype.factory(
    ItemLetterRelativeFrequencyCollector, None)
  )
)

# TODO: tweak
collector_weights = {
  ItemAverageCollector: 1.5,
  ItemLetterAverageCollector: math.sqrt
}


def main(*argv):
  """
  :param argv: tuple[str]
  :return: int
  """
  in_paths = [argv[0], argv[1]]
  must_validate = False

  # determine mode and/or output file
  if len(argv) > 2:
    if argv[2] == '--validate':
      must_validate = True
    else:
      sys.stdout = utilities.openspecial(argv[2], 'w')

  # determine collector weights to use
  if len(argv) > 3:
    with utilities.openspecial(argv[3], 'rb') as f:
      import pickle
      weights = pickle.load(f)
  else:
    weights = collector_weights


  # collect from both input files
  collectors = [collect(path, *collector_phase_description) for path in in_paths]

  # The first collector shall have the most columns.
  isreversed = len(collectors[0].merged_predecessors) < len(collectors[1].merged_predecessors)
  if isreversed:
    collectors.reverse()
    in_paths.reverse()

  # analyse collected data
  norms = MultiphaseCollector.results_norms(*collectors, weights=weights)
  if __debug__:
    print(*reversed(in_paths), sep=' / ', end='\n| ', file=sys.stderr)
    formatter = ufunctional.apply_memberfn(format, number_format)
    print(
      *['  '.join(itertools.imap(formatter, row)) for row in norms],
      sep=' |\n| ', end=' |\n\n', file=sys.stderr)

  # find minimal combination
  best_match = get_best_schema_mapping(norms)

  # print or validate best match
  if must_validate:
    validation_result = validate_result(in_paths, best_match[1], isreversed)
    print('\n{2} invalid, {3} impossible, and {4} missing matches, norm = {0:{1}}'.format(
      best_match[0], number_format, *validation_result))
    return int(validation_result[0] or validation_result[2])

  else:
    print('norm:', format(best_match[0], number_format), file=sys.stderr)
    print_result(best_match[1], isreversed)
    return 0


def collect(path, *phase_descriptions):
  """
  Collects info about the columns of the data set in file "path" according
  over multiple phases based on a description of those phases.

  :param path: str
  :param phase_descriptions: tuple[tuple[type | ItemCollector | callable]]
  :return: MultiphaseCollector
  """
  if __debug__:
    print(path, end=':\n', file=sys.stderr)

  with open(path, 'rb') as f:
    reader = csv.reader(f, delimiter=';', skipinitialspace=True)
    reader = itertools.imap(
      lambda list: uiterator.map_inplace(lambda item: DecodableUnicode(item.strip()), list),
      reader)
    multiphasecollector = MultiphaseCollector(reader)

    multiphasecollector(ColumnTypeItemCollector(len(multiphasecollector.rowset)))
    if __debug__:
      print(multiphasecollector.merged_predecessors, file=sys.stderr)

    for phase_description in phase_descriptions:
      multiphasecollector(*phase_description)
      if __debug__:
        print(multiphasecollector.merged_predecessors.as_str(number_format), file=sys.stderr)
    if __debug__:
      print(file=sys.stderr)

    return multiphasecollector


def get_best_schema_mapping(distance_matrix):
  """
  :param distance_matrix: list[list[float]]
  :return: (float, tuple[int])
  """
  assert operator.eq(*utilities.minmax(map(len, distance_matrix)))
  infinity = float('inf')

  maxI = len(distance_matrix)
  rangeJ = xrange(len(distance_matrix[0]))
  known_mappings = list(itertools.repeat(None, maxI))
  ismapped = list(itertools.repeat(False, len(rangeJ)))

  def sweep_row(i):
    if i == maxI:
      return 0, tuple(known_mappings)

    minlength = infinity
    minpath = None
    for j in itertools.ifilterfalse(ismapped.__getitem__, rangeJ):
      d = distance_matrix[i][j]
      if d is None or minlength <= d:
        continue

      known_mappings[i] = j
      ismapped[j] = True
      length, path = sweep_row(i + 1)
      ismapped[j] = False
      if path is None:
        continue

      length += d
      if length < minlength:
        minlength = length
        minpath = path

    return minlength, minpath

  return sweep_row(0)


def validate_result(in_paths, column_mappings, reversed=False, offset=1):
  """
  :param in_paths: list[str]
  :param column_mappings: list[int]
  :param reversed: bool
  :param offset: int
  :return: (int, int, int)
  """

  # build column mapping dictionary
  column_mappings = {k + offset: v + offset for k, v in enumerate(column_mappings)}
  if reversed:
    mapping = utilities.rdict(column_mappings)

  # read expected column mappings
  def read_descriptor(path):
    """
    :param path: str
    :return: dict[int, int]
    """
    with open(os.path.splitext(path)[0] + '_desc.txt') as f:
      return {
        int(mapped): int(original)
        for mapped, original
        in itertools.imap(ufunctional.apply_memberfn(str.split, ',', 2), f)
      }

  schema_desc = map(read_descriptor, in_paths)
  rschema_desc1 = utilities.rdict(schema_desc[1])
  invalid_count = 0
  impossible_count = 0

  # find mismatches
  for column_mapping in column_mappings.iteritems():
    found, expected = \
      itertools.starmap(dict.__getitem__,
        itertools.izip(schema_desc, column_mapping))
    assert found is schema_desc[0][column_mapping[0]]
    assert expected is schema_desc[1][column_mapping[1]]
    if found != expected:
      invalid_count += 0
      if found not in rschema_desc1:
        impossible_count += 1
        expected = None
    print('found {2} => {3}, expected {2} => {0} -- {1}'.format(
      expected, 'ok' if found == expected else 'MISMATCH!', *column_mapping))

  # find missing matches
  missing_count = len(schema_desc[0]) - len(column_mappings)
  if missing_count > 0:
    missing_count = 0
    missed_mappings = itertools.ifilterfalse(
      column_mappings.__contains__, schema_desc[0].iteritems())
    missed_mappings = uiterator.teemap(
      missed_mappings, None, rschema_desc1.get)
    missed_mappings = itertools.ifilterfalse(
        ufunctional.composefn(uoperator.second, uoperator.isnone), # rule out impossible mappings
        missed_mappings)
    for missing in missed_mappings:
      print('expected {} => {} -- MISSED!'.format(*missing))
      missing_count += 1

  return invalid_count, impossible_count, missing_count


def print_result(column_mappings, reversed=False, offset=1):
  """
  :param column_mappings: list[int]
  :param reversed: bool
  :param offset: int
  """
  column_mappings = [
    itertools.imap(str, xrange(offset, offset.__add__(len(column_mappings)))),
    itertools.imap(ufunctional.composefn(offset.__add__, str), column_mappings)
  ]
  if reversed:
    column_mappings.reverse()
  print(*itertools.starmap(','.join, itertools.izip(*column_mappings)), sep='\n')


if __name__ == '__main__':
  assert locale.getpreferredencoding().upper() == 'UTF-8'
  sys.exit(main(*sys.argv[1:]))
