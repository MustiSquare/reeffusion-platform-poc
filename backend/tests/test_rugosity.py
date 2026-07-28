import numpy as np
from app.processing.rugosity import rugosity_from_grid

def test_flat_grid_rugosity_is_one():
    r=rugosity_from_grid(np.zeros((8,8)))
    assert abs(r["rugosity"]-1.0) < 1e-9
