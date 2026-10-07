import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image, ImageDraw

from video_pipeline.common import ROOT, load_json, save_json, timestamp
from video_pipeline.compositing import style_video_graph
from video_pipeline.graphics import Graphics, glass_offer_layout, make_glass_offer
from video_pipeline.media import ffmpeg, frame


class GlassCardTests(unittest.TestCase):
    def setUp(self):
        self.brand = load_json(ROOT / 'video_pipeline/brands/brix/brand.json')
        self.brand['_directory'] = str(ROOT / 'video_pipeline/brands/brix')

    def test_every_scripts_rows_remain_until_the_end_of_its_offer(self):
        jobs = sorted((ROOT / 'video_pipeline/jobs').glob('*/A_original.json'))
        self.assertEqual(len(jobs), 12)
        with TemporaryDirectory() as tmp:
            for job_file in jobs:
                with self.subTest(job=job_file.stem):
                    job = load_json(job_file)
                    words = load_json(ROOT / job['alignment']['words'])
                    duration = words[-1]['end'] + 2
                    offer = job['creative']['offer']
                    graphics = Graphics(self.brand, duration)
                    make_glass_offer(graphics, offer, words, duration, Path(tmp))
                    layout = load_json(Path(tmp) / 'offer_layout.json')
                    self.assertEqual(len(layout['rows']), 3 if job_file.parent.name.startswith('plumbing') else 4)
                    self.assertEqual(layout['start'],layout['rows'][0]['start'])
                    self.assertNotIn('hook',job['creative'])
                    self.assertNotIn('intro',offer)
                    for row in layout['rows']:
                        # Inspect the ASS actually delivered to FFmpeg, including
                        # the retained first row after the final row is revealed.
                        events = [e for e in graphics.events if e.endswith('}' + row['text'])]
                        self.assertEqual(len(events), 1)
                        self.assertEqual(events[0].split(',')[1:3],
                                         [timestamp(row['start']), timestamp(layout['end'])])
                        self.assertLessEqual(row['start'], layout['rows'][-1]['start'])
                        self.assertGreater(row['end'], layout['rows'][-1]['start'] + .5)

    def test_invalid_row_timing_and_caption_overlap_are_rejected(self):
        offer = {'start': 0, 'end': 3, 'benefits': [
            {'start': 1.5, 'text': 'First'}, {'start': 1, 'text': 'Second'}]}
        with self.assertRaisesRegex(ValueError, 'start in order'):
            glass_offer_layout(self.brand, offer, [], 3)
        offer['benefits'][1]['start'] = 2
        brand = copy.deepcopy(self.brand)
        brand['layout']['offer_card']['row_top'] = 1000
        with self.assertRaisesRegex(ValueError, 'caption area'):
            glass_offer_layout(brand, offer, [], 3)

    def test_real_compositor_blurs_only_the_rounded_card_during_its_interval(self):
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            size = (270, 480)
            striped = Image.new('RGB', size)
            draw = ImageDraw.Draw(striped)
            for x in range(0, size[0], 4):
                draw.rectangle((x, 0, x + 1, size[1] - 1), fill='white')
            striped.save(project / 'source.png')
            for name in ('gradient.png', 'brand_header.png'):
                Image.new('RGBA', size).save(project / name)
            mask = Image.new('L', (160, 160))
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, 159, 159), radius=20, fill=255)
            mask.save(project / 'offer_mask.png')
            save_json(project / 'offer_layout.json', {
                'style': 'glass', 'bounds': [160, 480, 640, 640],
                'blur_sigma': 24, 'tint_opacity': .55, 'tint_color': '#061c2b',
                'start': .5, 'end': 1.5, 'fade_ms': 100})
            (project / 'fonts').mkdir()
            Graphics(self.brand, 2).write(project / 'graphics.ass')
            graph = style_video_graph(project, *size).rstrip(';')
            output = project / 'composite.mp4'
            ffmpeg(['-loop', '1', '-framerate', '10', '-i', project / 'source.png',
                    '-i', project / 'gradient.png', '-i', project / 'brand_header.png',
                    '-i', project / 'offer_mask.png', '-filter_complex_threads', '1',
                    '-filter_complex', graph, '-map', '[v]', '-t', '2',
                    '-c:v', 'libx264', '-crf', '0', '-threads', '1', output], cwd=project)
            before, during, after = [np.asarray(frame(output, t, width=270)).astype(float)
                                     for t in (.2, 1, 1.8)]
            center = np.s_[150:250, 70:170, :]
            self.assertLess(during[center].std(), before[center].std() * .15)
            self.assertLess(during[center].mean(), before[center].mean() * .7)
            self.assertLess(np.abs(before - after).mean(), 1)
            # Full-frame pixels and the clipped corner stay sharp and unchanged.
            for area in (np.s_[:100, :, :], np.s_[120:123, 40:43, :]):
                self.assertLess(np.abs(before[area] - during[area]).mean(), 2)


if __name__ == '__main__':
    unittest.main()
