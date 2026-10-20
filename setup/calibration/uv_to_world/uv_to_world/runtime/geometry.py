from math import isfinite, sqrt


def normalize(vector):
    if len(vector) != 3 or not all(isfinite(value) for value in vector):
        raise ValueError('vector must contain three finite values')
    length = sqrt(sum(value * value for value in vector))
    if length < 1.0e-12:
        raise ValueError('cannot normalize a zero vector')
    return tuple(value / length for value in vector)


def rotate_by_quaternion(vector, quaternion):
    """Rotate a 3-vector by an (x, y, z, w) quaternion."""
    if (len(vector) != 3 or len(quaternion) != 4 or
            not all(isfinite(value) for value in (*vector, *quaternion))):
        raise ValueError('rotation requires finite 3-vector and quaternion')
    x, y, z, w = quaternion
    norm = sqrt(x * x + y * y + z * z + w * w)
    if norm < 1.0e-12:
        raise ValueError('invalid zero quaternion')
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    vx, vy, vz = vector
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def ray_plane_intersection(origin, direction, normal, offset):
    """Intersect origin+t*direction with normal dot point + offset = 0."""
    if (len(origin) != 3 or len(direction) != 3 or len(normal) != 3 or
            not all(isfinite(value) for value in (*origin, *direction, *normal)) or
            not isfinite(offset)):
        raise ValueError('ray and plane must contain finite values')
    normal_length = sqrt(sum(value * value for value in normal))
    if normal_length < 1.0e-12:
        raise ValueError('cannot normalize a zero vector')
    normal = tuple(value / normal_length for value in normal)
    offset /= normal_length
    denominator = sum(a * b for a, b in zip(normal, direction))
    if abs(denominator) < 1.0e-9:
        raise ValueError('camera ray is parallel to the configured plane')
    distance = -(sum(a * b for a, b in zip(normal, origin)) + offset)
    distance /= denominator
    if distance <= 0.0:
        raise ValueError('plane intersection lies behind the camera')
    point = tuple(o + distance * d for o, d in zip(origin, direction))
    if not all(isfinite(value) for value in point):
        raise ValueError('plane intersection is not finite')
    return point


def ray_plane_incidence(direction, normal):
    """Return abs(cos(theta)) for a ray direction and plane normal."""
    direction = normalize(direction)
    normal = normalize(normal)
    return abs(sum(a * b for a, b in zip(normal, direction)))
