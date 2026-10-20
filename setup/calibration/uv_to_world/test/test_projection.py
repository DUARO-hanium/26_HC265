from uv_to_world.plane_projection_node import pixel_to_camera_ray


class FakeCameraModel:
    def __init__(self):
        self.rectified = []
        self.projected = []

    def rectify_point(self, pixel):
        self.rectified.append(pixel)
        return (pixel[0] + 1.0, pixel[1] + 2.0)

    def project_pixel_to_3d_ray(self, pixel):
        self.projected.append(pixel)
        return (pixel[0], pixel[1], 1.0)


def test_rectified_uv_projects_directly():
    model = FakeCameraModel()

    ray = pixel_to_camera_ray(model, (10.0, 20.0), True)

    assert model.rectified == []
    assert model.projected == [(10.0, 20.0)]
    assert ray == (10.0, 20.0, 1.0)


def test_raw_uv_is_rectified_before_projection():
    model = FakeCameraModel()

    ray = pixel_to_camera_ray(model, (10.0, 20.0), False)

    assert model.rectified == [(10.0, 20.0)]
    assert model.projected == [(11.0, 22.0)]
    assert ray == (11.0, 22.0, 1.0)
