#!/usr/bin/python -OO
from __future__ import print_function, absolute_import
import sys, os.path, signal
import operator, collections
import csv
from itertools import repeat
from functools import partial as partialfn

import utilities.file, utilities.operator
from utilities import infinity
from utilities.iterator import each, map_inplace
from utilities.functional import memberfn, composefn
from collector import verbosity
from collector.multiphase import MultiphaseCollector

if __debug__:
  import timeit


default_timelimit = 60
number_format = '.3e'
__interrupted = False



def main(argv, time_limit=None):
  # parse arguments
  argv = collections.deque(argv)

  # action to perform
  if argv[0].startswith('--'):
    action = argv.popleft()[2:]
  else:
    # default action; set up alarm handler
    action = None
    global __interrupted
    __interrupted = False
    if time_limit > 0:
      signal.signal(signal.SIGALRM, __timeout_handler)
      if signal.alarm(time_limit):
        raise RuntimeError('Who set the alarm before us?!!')

  # input files
  in1 = argv.popleft()
  in2 = argv.popleft()

  # output file
  if argv:
    forbidden_suffix = '.py'
    if (len(argv[0]) > len(forbidden_suffix) and
        argv[0][-len(forbidden_suffix):] == forbidden_suffix
    ):
      print("Error: To prevent usage errors, we don't allow writing to *{} files." \
        .format(forbidden_suffix), file=sys.stderr)
      return 2
    out = utilities.file.openspecial(argv.popleft(), 'w')
  else:
    out = sys.stdout


  # read and analyse data
  rv = schema_matching(action, in1, in2, argv, out)
  if (__interrupted):
    print(
      'The time limit of', time_limit, 'seconds was reached. '
      'The results may be incomplete or inaccurate.',
      file=sys.stderr)
  return rv



def schema_matching(action, in1, in2, collector_descriptions=None, out=sys.stdout):
  in_paths = [in1, in2]

  if collector_descriptions is None:
    collector_descriptions = ()
  elif collector_descriptions:
    collector_descriptions = collections.deque(collector_descriptions)

  # determine collector descriptions to use
  collector_description = get_collector_description(
    collector_descriptions.popleft() if collector_descriptions else None)

  # read and analyse data
  collectors, isreversed, best_match = \
    collect_analyse_match(in_paths, collector_description, out)
  best_match_norm, best_match = best_match
  if isreversed:
    in_paths.reverse()

  # print or validate best match
  if action is None:
    if verbosity >= 1:
      print('norm:', format(best_match_norm, number_format), file=sys.stderr)
    print_result(best_match, isreversed, out)

  elif action == 'validate':
    invalid_count, impossible_count, missing_count = \
      validate_result(in_paths, best_match, best_match_norm, out)
    return int(bool(invalid_count | missing_count))

  elif action == 'compare-descriptions':
    return compare_descriptions(in_paths, collectors, collector_descriptions,
      (collector_description, best_match_norm, best_match), out)

  else:
    print('Unknown action:', action, file=sys.stderr)
    return 2

  return 0


def get_collector_description(srcpath=None):
  """
  :param srcpath: str
  :return: dict
  """
  if srcpath is None or srcpath == ':':
    from collector.description import default as collector_description
  elif srcpath.startswith(':'):
    import importlib
    collector_description = importlib.import_module(srcpath[1:])
  else:
    import os, imp
    import collector.description as parent_package # needs to be imported before its child modules
    with open(srcpath) as f:
      module_name = \
        '{0}._anonymous_{1.st_dev}_{1.st_ino}'.format(
          parent_package.__name__, os.fstat(f.fileno()))
      collector_description = imp.load_source(module_name, srcpath, f)
    assert isinstance(getattr(collector_description, '__file__', None), str)

  utilities.setattr_default(collector_description, '__file__', '<unknown file>')
  if not hasattr(collector_description, 'descriptions'):
    raise NameError(
      "The collector description module doesn't contain any collector description.",
      collector_description, collector_description.__file__,
      "missing attribute 'description'")

  return collector_description


def collect_analyse_match(collectors, collector_descriptions, out=sys.stdout):
  """
  :param collectors: list[str | MultiphaseCollector]
  :param collector_descriptions: object
  :return: list[MultiphaseCollector], bool, tuple[int]
  """
  assert isinstance(collectors, collections.Sequence) and len(collectors) == 2
  collect_functor = memberfn(collect, collector_descriptions.descriptions, out)

  if isinstance(collectors[0], MultiphaseCollector):
    assert isinstance(collectors[1], MultiphaseCollector)
    each(collect_functor, collectors)
  else:
    collectors = list(map(collect_functor, collectors))

  # The first collector shall have the least columns.
  isreversed = len(collectors[0].merged_predecessors) > len(collectors[1].merged_predecessors)
  if isreversed:
    collectors.reverse()

  # analyse collected data
  norms = MultiphaseCollector.results_norms(*collectors,
    weights=collector_descriptions.weights)
  if verbosity >= 1:
    print(collectors[1].name, collectors[0].name, sep=' / ', end='\n| ', file=sys.stderr)
    formatter = memberfn(format, number_format)
    print(*('  '.join(map(formatter, row)) for row in norms),
      sep=' |\n| ', end=' |\n\n', file=sys.stderr)

  # find minimal combination
  return collectors, isreversed, get_best_schema_mapping(norms)


def collect(src, collector_descriptions, out=sys.stdout):
  """
  Collects info about the columns of the data set in file "path" according
  over multiple phases based on a description of those phases.

  :param src: str, MultiphaseCollector
  :param collector_descriptions: tuple[type | ItemCollector | callable]
  :return: MultiphaseCollector
  """
  if isinstance(src, MultiphaseCollector):
    multiphasecollector = src.reset()

  else:
    if verbosity >= 2:
      print(src, end=':\n', file=sys.stderr)

    with open(src) as f:
      reader = csv.reader(f, delimiter=';', skipinitialspace=True)
      reader = map(partialfn(map_inplace, str.strip), reader)
      multiphasecollector = MultiphaseCollector(reader, os.path.basename(src))

  multiphasecollector.do_phases(collector_descriptions,
    print_phase_results if verbosity >= 2 else None)
  if verbosity >= 2:
    print(file=sys.stderr)

  return multiphasecollector


def print_phase_results(multiphasecollector):
  print(multiphasecollector.merged_predecessors.as_str(number_format), file=sys.stderr)


def get_best_schema_mapping(distance_matrix):
  """
  :param distance_matrix: list[list[float]]
  :return: (float, tuple[int])
  """
  assert operator.eq(*utilities.minmax(map(len, distance_matrix)))
  successor = (1).__add__
  predecessor = (1).__rsub__

  maxI = len(distance_matrix) # row count
  maxJ = len(distance_matrix[0]) # column count
  assert maxI >= maxJ
  rangeJ = range(maxJ)
  known_mappings = list(repeat(None, maxJ))

  def iter_unmapped():
    return filter(lambda j: known_mappings[j] is None, rangeJ)

  def sweep_row(i, skippable_count):
    if __interrupted or skippable_count < 0:
      return infinity, None
    if i == maxI:
      return 0, tuple(known_mappings)

    # try to skip column j
    minlength, minpath = sweep_row(successor(i), predecessor(skippable_count))

    for j in iter_unmapped():
      if __interrupted:
        break
      d = distance_matrix[i][j]
      if d is not None:
        known_mappings[j] = i
        length, path = sweep_row(successor(i), skippable_count)
        known_mappings[j] = None
        length += d
        if length < minlength:
          assert path is not None
          minlength = length
          minpath = path
    return minlength, minpath

  return sweep_row(0, maxI - maxJ)


def validate_result(in_paths, found_mappings, norm, out=sys.stdout, offset=1):
  """
  :param in_paths: list[str]
  :param found_mappings: list[int]
  :param offset: int
  :return: (int, int, int)
  """

  # read expected column mappings
  def read_descriptor(path):
    """
    :param path: str
    :return: dict[int, int]
    """
    with open(os.path.splitext(path)[0] + '_desc.txt') as f:
      return {
        int(mapped): int(original)
        for mapped, original in map(memberfn(str.split, ',', 1), f)
      }

  schema_desc = tuple(map(read_descriptor, in_paths))
  rschema_desc = tuple(map(utilities.rdict, schema_desc))

  # build column mapping dictionary
  found_mappings = {k + offset: v + offset for k, v in enumerate(found_mappings) if v is not None}
  invalid_count = 0
  impossible_count = 0

  # find mismatches
  for found_mapping in found_mappings.items():
    original_mapping = tuple(map(dict.__getitem__, schema_desc, found_mapping))
    expected = rschema_desc[1].get(original_mapping[0])
    if expected is None:
      impossible_count += 1
    else:
      invalid_count += operator.ne(*original_mapping)

    print('found {2} => {3}, expected {2} => {0} -- {1}'.format(
      expected, 'ok' if found_mapping[1] == expected else 'MISMATCH!', *found_mapping),
      file=out)

  # find missing matches
  missing_count = 0
  for k in rschema_desc[0].keys() | rschema_desc[1].keys():
    v = rschema_desc[1].get(k)
    k = rschema_desc[0].get(k)
    if k is not None and v is not None and k not in found_mappings:
      print('expected {} => {} -- MISSED!'.format(k, v))
      missing_count += 1

  print('\n{} invalid, {} impossible, and {} missing matches, norm = {:{}}'.format(
    invalid_count, impossible_count, missing_count, norm, number_format),
    file=out)

  return invalid_count, impossible_count, missing_count


def compare_descriptions(in_paths, collectors, to_compare, desc=None, out=sys.stdout):
  """
  :param collectors: list[str | MultiphaseCollector]
  :param to_compare: tuple[str]
  :param desc: dict, float, tuple(int)
  :return:
  """
  descriptions = []

  if desc:
    desc, best_match_norm, best_match = desc
    if not to_compare:
      from collector.description import default as default_description
      if os.path.samefile(desc.__file__, default_description.__file__):
        print("Error: I won't compare the default description to itself.", file=sys.stderr)
        return 2

    invalid_count, _, missing_count = \
      validate_result(in_paths, best_match, best_match_norm, out)
    print_description_comment(desc, out)
    descriptions.append((desc, invalid_count + missing_count, best_match_norm))

  for desc in map(get_collector_description, to_compare or (None,)):
    collectors, _, best_match = collect_analyse_match(collectors, desc, out)
    best_match_norm, best_match = best_match
    invalid_count, _, missing_count = \
      validate_result(in_paths, best_match, best_match_norm, out)
    print_description_comment(desc, out)
    descriptions.append((desc, invalid_count + missing_count, best_match_norm))

  i = 1
  last_error_count = None
  descriptions.sort(key=utilities.operator.getitemfn(slice(1, 3)))
  for desc in descriptions:
    print('{}. {}, errors={}, norm={:{}}'.format(
      i, desc[0].__file__, desc[1], desc[2], number_format),
      file=out)
    i += last_error_count != desc[1]
    last_error_count = desc[1]

  return 0



def print_result(column_mappings, reversed=False, out=sys.stdout, offset=1):
  """
  :param column_mappings: list[int]
  :param reversed: bool
  :param offset: int
  """
  if not column_mappings:
    return

  column_mappings = [
    map(str, range(offset, offset.__add__(len(column_mappings)))),
    map(composefn(offset.__add__, str), column_mappings)
  ]
  if reversed:
    column_mappings.reverse()
  print(*map(','.join, zip(*column_mappings)), sep='\n', file=out)


def print_description_comment(desc, out):
  print('... with collector descriptions and weights from {} ({}).'.format(
    desc.__file__, desc.__name__),
    end='\n\n', file=out)


def __timeout_handler(signum, frame):
  if signum == signal.SIGALRM:
    global __interrupted
    __interrupted = timeit.default_timer() if __debug__ else True


if __name__ == '__main__':
  rv = main(sys.argv[1:], default_timelimit)
  if __debug__ and __interrupted:
    print('INFO:', timeit.default_timer() - __interrupted,
      'seconds between interruption and program termination.',
      file=sys.stderr)
  sys.exit(rv)
