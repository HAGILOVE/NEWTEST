import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from aether.core.logging import configure

configure("WARNING")


def occ_available() -> bool:
    from aether.geometry.kernel import available
    return available()


needs_occ = pytest.mark.skipif(not occ_available(),
                               reason="gmsh/OpenCASCADE backend not installed")
