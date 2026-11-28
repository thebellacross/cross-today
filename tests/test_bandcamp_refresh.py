import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('refresh_bandcamp', Path(__file__).parents[1] / 'scripts/refresh_bandcamp.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BandcampRefreshTest(unittest.TestCase):
    def test_lazy_images_relative_protocol_and_html_attribute_variants(self):
        page = "<li class='square music-grid-item'><a href='/album/cross'><img src='placeholder' data-original='//f4.bcbits.com/img/a0409425978_2.jpg'><p class='title'>CROSS &amp; more</p></a></li>"
        item = module.releases(page, 'https://bellacrossmusic.bandcamp.com/')[0]
        self.assertEqual(item['title'], 'CROSS & more')
        self.assertEqual(item['cover_source'], 'https://f4.bcbits.com/img/a0409425978_16.jpg')

    def test_new_release_is_added_without_changing_artist_identity(self):
        base = 'https://bellacrossmusic.bandcamp.com/'
        grid = '<li class="music-grid-item"><a href="/album/cross"><img src="https://f4.bcbits.com/img/a0409425978_2.jpg"><p class="title">CROSS</p></a></li>'
        detail = '<script type="application/ld+json">{"name":"CROSS","datePublished":"22 Nov 2026 00:00:00 GMT"}</script>'
        resources = {base + 'music': grid.encode(), base + 'album/cross': detail.encode(), 'https://f4.bcbits.com/img/a0409425978_16.jpg': b'\xff\xd8\xffcover'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = {'name': 'CROSS', 'bandcamp': base, 'avatar': 'assets/artist/bellacross.jpg', 'bio': '', 'albums': []}
            (root / 'artist.json').write_text(json.dumps(before))
            self.assertEqual(module.refresh(root, resources.__getitem__), 1)
            result = json.loads((root / 'artist.json').read_text())
            self.assertEqual(result['name'], before['name'])
            self.assertEqual(result['avatar'], before['avatar'])
            self.assertEqual(result['albums'][0]['released'], '2026-11-22')
            self.assertEqual((root / result['albums'][0]['cover']).read_bytes(), b'\xff\xd8\xffcover')
            # Existing date and cover need no repeat downloads on a later build.
            self.assertEqual(module.refresh(root, lambda url: resources[url] if url.endswith('/music') else self.fail(url)), 1)
            saved = (root / 'artist.json').read_bytes()
            with self.assertRaises(ValueError):
                module.refresh(root, lambda url: b'<html>Temporarily unavailable</html>')
            self.assertEqual((root / 'artist.json').read_bytes(), saved)


if __name__ == '__main__':
    unittest.main()
