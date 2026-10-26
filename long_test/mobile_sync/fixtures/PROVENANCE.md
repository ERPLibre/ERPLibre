# Fixtures

`photo-2400x1600.jpg` is generated, not photographed: a colour gradient
(red left to right, green top to bottom, blue constant), 2400 × 1600 px,
JPEG quality 90, no EXIF. Its long side is over Odoo's 1920 px image
reduction, so a test sees whether the server kept the original. The
command, run from the ERPLibre root, gives the same bytes each time with
the same Pillow (12.3.0):

```bash
.venv.odoo18.0_python3.12.10/bin/python -c "
from PIL import Image
w, h = 2400, 1600
r = Image.linear_gradient('L').rotate(90).resize((w, h))
g = Image.linear_gradient('L').resize((w, h))
b = Image.new('L', (w, h), 128)
Image.merge('RGB', (r, g, b)).save('long_test/mobile_sync/fixtures/photo-2400x1600.jpg', quality=90)
"
```

SHA-1: `fe45900672d7c2f22d2209b56c664a9e6279e437`.
