from build123d import Compound, Cylinder, Sphere


def build_model():
    body_radii, body_center = (19, 9, 12), (0, 0, 13)
    head_radii, head_center = (9, 8, 9), (14, 0, 27)
    muzzle_radii, muzzle_center = (5, 5, 3), (22, 0, 24)
    ear_radii, ear_center = (3, 2, 6), (11, -1, 35)
    tail_radii, tail_center = (7, 2.5, 2.5), (-19, 0, 21)
    body = Sphere(1).scale(body_radii).translate(body_center)
    head = Sphere(1).scale(head_radii).translate(head_center)
    muzzle = Sphere(1).scale(muzzle_radii).translate(muzzle_center)
    ear = Sphere(1).scale(ear_radii).translate(ear_center)
    tail = Sphere(1).scale(tail_radii).translate(tail_center)
    legs = [
        Cylinder(2.5, 13).translate((10, -3.5, 6.5)),
        Cylinder(2.5, 13).translate((10, 3.5, 6.5)),
        Cylinder(3, 15).translate((-11, -3.5, 7.5)),
        Cylinder(3, 15).translate((-11, 3.5, 7.5)),
    ]
    return Compound([body, head, muzzle, ear, tail, legs[0], legs[1], legs[2], legs[3]])
