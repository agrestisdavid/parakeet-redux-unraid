from copy import deepcopy
from benchmarks.whisper_cold_start import signature


def fixture():
    return {'Id': 'example', 'Image': 'sha256:test', 'Config': {'Env': ['MODEL=fixed']},
            'HostConfig': {'Memory': 123}, 'Mounts': [
                {'Destination': '/a', 'Source': '/first', 'RW': True},
                {'Destination': '/b', 'Source': '/second', 'RW': False}]}


def test_mount_order_is_not_configuration_change():
    before = fixture()
    after = deepcopy(before)
    after['Mounts'].reverse()
    assert signature(before) == signature(after)
    assert before['Mounts'][0]['Destination'] == '/a'


def test_real_mount_or_config_changes_are_detected():
    before = fixture()
    after = deepcopy(before)
    after['Mounts'][0]['RW'] = False
    assert signature(before) != signature(after)
    after = deepcopy(before)
    after['Config']['Env'] = ['MODEL=changed']
    assert signature(before) != signature(after)
