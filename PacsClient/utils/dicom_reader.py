"""Pure DICOM read compatibility; callers retain their execution-domain ownership.

Some exports omit the final encapsulated Pixel Data delimiter. Recover only
complete, explicitly bounded items ending exactly at EOF. Never rewrite a file,
guess an offset by searching bytes, change transfer syntax, or accept truncation.
"""
from __future__ import annotations

import logging
import os
import struct
import warnings

import pydicom
from pydicom.filereader import read_partial
from pydicom.tag import Tag

_LOG = logging.getLogger(__name__)
_PIXEL = Tag(0x7FE0, 0x0010)
_MAX_VALUE_BYTES = 256 * 1024 * 1024
_MAX_ITEMS = 65536


def _complete_eof_value(path, *, force, specific_tags=None):
    """Return validated encapsulated bytes or None, without interpreting pixels."""
    with open(path, 'rb') as stream:
        before = os.fstat(stream.fileno())
        found = []

        def at_pixel(tag, vr, length):
            if tag == _PIXEL:
                found.append((vr, length))
                return True
            return False

        header = read_partial(stream, stop_when=at_pixel, force=force,
                              specific_tags=specific_tags)
        syntax = getattr(header.file_meta, 'TransferSyntaxUID', None)
        if (not syntax or not syntax.is_compressed or
                not found or found[0] != ('OB', 0xFFFFFFFF)):
            return None
        # read_partial rewinds to the element start, determined by the parser.
        pixel_header = stream.read(12)
        if pixel_header != b'\xe0\x7f\x10\x00OB\x00\x00\xff\xff\xff\xff':
            return None
        start = stream.tell()
        end = os.fstat(stream.fileno()).st_size
        if not 16 <= end - start <= _MAX_VALUE_BYTES:
            return None
        offsets = None
        fragment_starts = set()
        first_fragment = None
        for index in range(_MAX_ITEMS):
            position = stream.tell()
            item = stream.read(8)
            if len(item) != 8:
                return None
            group, element, length = struct.unpack('<HHI', item)
            if ((group, element) != (0xFFFE, 0xE000) or length == 0xFFFFFFFF
                    or length % 2 or length > end - stream.tell()):
                return None
            if index == 0:
                if length % 4 or length > _MAX_ITEMS * 4:
                    return None
                table = stream.read(length)
                offsets = struct.unpack('<' + 'I' * (length // 4), table)
            else:
                if length == 0:
                    return None
                if first_fragment is None:
                    first_fragment = position
                fragment_starts.add(position - first_fragment)
                stream.seek(length, os.SEEK_CUR)
            if stream.tell() == end:
                if (first_fragment is None or any(o not in fragment_starts for o in offsets)
                        or list(offsets) != sorted(set(offsets))):
                    return None
                stream.seek(start)
                value = stream.read(end - start)
                # A concurrent truncation must not turn into a successful recovery.
                after = os.fstat(stream.fileno())
                if (len(value) != end - start or before.st_size != after.st_size
                        or before.st_mtime_ns != after.st_mtime_ns):
                    return None
                return header, value
        return None


def read_dicom(path, **kwargs):
    """pydicom.dcmread plus narrowly validated missing-delimiter recovery.

    Header-only and selected non-pixel reads retain their original semantics.
    Call from existing I/O/decode workers, not a new GUI-thread read path.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message=r'End of file reached before delimiter .*',
                                category=UserWarning)
        dataset = pydicom.dcmread(path, **kwargs)
    tags = kwargs.get('specific_tags')
    wants_pixels = not tags or any(Tag(t) == _PIXEL for t in tags)
    syntax = getattr(getattr(dataset, 'file_meta', None), 'TransferSyntaxUID', None)
    if ('PixelData' in dataset or kwargs.get('stop_before_pixels') or not wants_pixels
            or not isinstance(path, (str, os.PathLike))
            or not syntax or not syntax.is_compressed):
        return dataset
    try:
        recovered = _complete_eof_value(path, force=bool(kwargs.get('force', False)),
                                        specific_tags=tags)
    except (OSError, ValueError, EOFError, struct.error):
        recovered = None
    if recovered is not None:
        # Use metadata and pixels from the same open descriptor, never combine
        # an earlier read's header with a replacement file's pixel payload.
        dataset, value = recovered
        dataset.add_new(_PIXEL, 'OB', value)
        dataset[_PIXEL].is_undefined_length = True
        _LOG.debug('[DICOM_EOF_RECOVERY] complete_fragment_value_restored')
    return dataset
