import copy
import unittest

from video_pipeline.common import ROOT,load_json
from video_pipeline.geometry import canvas_size,crop_rect
from video_pipeline.remix import verify_audio_only


class FormatTests(unittest.TestCase):
    def test_full_and_preview_formats_keep_exact_aspect_and_even_dimensions(self):
        brand=load_json(ROOT/'video_pipeline/brands/brix/brand.json')
        for height in (1350,1920):
            b=copy.deepcopy(brand);b['video']['height']=height
            for preview in (False,True):
                w,h=canvas_size(b,preview)
                self.assertEqual(w%2,0)
                self.assertEqual(h%2,0)
                self.assertAlmostEqual(w/h,1080/height)

    def test_four_by_five_reframes_landscape_and_portrait_without_stretching(self):
        for iw,ih in ((1920,1080),(1080,1920),(1000,1000)):
            for center in ((.5,.5),(0,0),(1,1)):
                x,y,cw,ch=crop_rect(iw,ih,1080,1350,center)
                self.assertAlmostEqual(cw/ch,4/5,delta=.002)
                self.assertGreaterEqual(x,0)
                self.assertGreaterEqual(y,0)
                self.assertLessEqual(x+cw,iw)
                self.assertLessEqual(y+ch,ih)
        old=crop_rect(1920,1080,1080,1920,(.5,.5))
        new=crop_rect(1920,1080,1080,1350,(.5,.5))
        self.assertGreater(new[2],old[2])

    def test_all_ad_pairs_change_only_music_and_use_one_ad_folder(self):
        batch=load_json(ROOT/'video_pipeline/batches/meta_4x5.json')
        self.assertEqual(len(batch['ads']),12)
        for item in batch['ads']:
            a,b=[load_json(ROOT/item['jobs'][key]) for key in ('A','B')]
            verify_audio_only(b,a)
            for job in (a,b):
                self.assertEqual((ROOT/job['output']).parent,ROOT/'output'/item['ad']/'output')
                self.assertIn('_4x5_',job['output'])
                self.assertEqual(job['music']['gain'],.8)
            self.assertEqual(a['music']['profile'],'original')
            self.assertEqual(b['music']['profile'],'relaxed_groove')


if __name__=='__main__':unittest.main()
