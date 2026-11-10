"""Copy immutable original assets into the temporary, offline review harness."""
from pathlib import Path
import shutil

root = Path('.review/archive')
review = Path('.review')
fixtures = [
    ('84da6b5d-046a-4fe1-bf3f-61c2036e789b', 'affections-source.html', [(1, 'portrait.jpg')]),
    ('e94f1b0c-ab32-4323-8d3b-4bc60ea82ace', 'lion-source.html', [(1, 'lion.jpg'), (2, 'lion-second.jpg')]),
    ('ba78ab40-e1d1-4b82-9b71-194439cd6f86', 'tragedy-source.html', [(1, 'tragedy-boy.jpg'), (2, 'tragedy-family.jpg')]),
    ('533e049a-b6ef-473a-ad9f-6b62f7c04d83', 'healing-source.html', [(1, 'healing.jpg')]),
]
for identity, source, images in fixtures:
    shutil.copyfile(root / 'content/articles' / f'{identity}.html', review / source)
    for sequence, destination in images:
        shutil.copyfile(root / 'public/images/articles' / f'{identity}-{sequence}.jpg', review / destination)
