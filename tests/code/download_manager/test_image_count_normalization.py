"""Per-series image-count normalization tolerates server key-name variants.

Regression: studies/series whose count arrived under an alternate key (e.g.
NumberOfInstances) collapsed to 0 in Download Manager metadata, breaking
totals/progress. See modules/download_manager/network/grpc_client.py.
"""

from modules.download_manager.network.grpc_client import _normalize_image_count


def test_canonical_key():
    assert _normalize_image_count({"image_count": 52}) == 52


def test_alternate_keys():
    assert _normalize_image_count({"ImageCount": 30}) == 30
    assert _normalize_image_count({"number_of_instances": 12}) == 12
    assert _normalize_image_count({"NumberOfInstances": 7}) == 7
    assert _normalize_image_count({"instance_count": 5}) == 5
    assert _normalize_image_count({"num_images": 9}) == 9


def test_string_and_float_values():
    assert _normalize_image_count({"image_count": "88"}) == 88
    assert _normalize_image_count({"image_count": " 14 "}) == 14
    assert _normalize_image_count({"image_count": 30.0}) == 30


def test_canonical_wins_over_alternate():
    # First non-empty key in priority order is used.
    assert _normalize_image_count({"image_count": 52, "NumberOfInstances": 999}) == 52


def test_missing_or_empty_defaults_zero():
    assert _normalize_image_count({}) == 0
    assert _normalize_image_count({"image_count": None}) == 0
    assert _normalize_image_count({"image_count": ""}) == 0
    assert _normalize_image_count({"unrelated": 5}) == 0


def test_garbage_and_negative_safe():
    assert _normalize_image_count({"image_count": "abc"}) == 0
    assert _normalize_image_count({"image_count": -3, "ImageCount": 4}) == 4  # skip negative, take next
    assert _normalize_image_count("not a dict") == 0


def test_falls_through_empty_then_alternate():
    # image_count present-but-empty must not block the alternate key.
    assert _normalize_image_count({"image_count": "", "NumberOfInstances": 21}) == 21
