"""Decode DDS with Pillow; sRGB DXGI tags are mapped to UNORM twins in memory (payload unchanged, raw values)."""
import io, struct
from PIL import Image
import numpy as np
SRGB = {72: 71, 75: 74, 78: 77, 99: 98, 29: 28, 91: 87, 93: 88}
def load(path):
    d = bytearray(open(path, "rb").read())
    if d[84:88] == b"DX10":
        f = struct.unpack_from("<I", d, 128)[0]
        if f in SRGB:
            struct.pack_into("<I", d, 128, SRGB[f])
    im = Image.open(io.BytesIO(bytes(d))); im.load()
    return np.asarray(im.convert("RGBA"))
