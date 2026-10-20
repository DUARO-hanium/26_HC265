import pytest

from uv_to_world.calibrated_tf_node import validate_calibration


def valid_document():
    return {
        'calibration': {
            'quality_passed': True,
            'parent_frame': 'link0',
            'child_frame': 'camera1_optical_frame',
            'translation': [0.1, 0.2, 0.3],
            'quaternion_xyzw': [0.0, 0.0, 0.0, 1.0],
        },
    }


def test_accepts_valid_transform():
    result = validate_calibration(valid_document())
    assert result['parent_frame'] == 'link0'
    assert result['quaternion_xyzw'] == pytest.approx([0.0, 0.0, 0.0, 1.0])


@pytest.mark.parametrize(
    'field,value,expected',
    [
        ('quality_passed', False, 'quality'),
        ('parent_frame', '', 'parent_frame'),
        ('translation', [0.0, 0.0], 'translation'),
        ('translation', [0.0, float('nan'), 0.0], 'finite'),
        ('quaternion_xyzw', [0.0, 0.0, 0.0, 0.0], 'norm'),
        ('quaternion_xyzw', [0.0, 0.0, 0.0, 2.0], 'normalized'),
    ],
)
def test_rejects_invalid_transform(field, value, expected):
    document = valid_document()
    document['calibration'][field] = value
    with pytest.raises(ValueError, match=expected):
        validate_calibration(document)
