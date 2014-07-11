from __future__ import absolute_import
import sys, codecs
from .string import DecodableUnicode


def is_write_mode(mode):
  return 'w' in mode or 'a' in mode


__openspecial_names = {'/dev/std' + s: getattr(sys, 'std' + s) for s in ('in', 'out', 'err')}

def openspecial(path, mode='r', *args):
  if path == '-':
    return sys.stdout if is_write_mode(mode) else sys.stdin
  else:
    f = __openspecial_names.get(path)
    return open(path, mode, *args) if f is None else f


def fix_file_encoding(file):
  if not file.encoding:
    wrapper_factory = codecs.getwriter if is_write_mode(file.mode) else codecs.getreader
    file = wrapper_factory(DecodableUnicode.default_encoding)(file)
  return file
