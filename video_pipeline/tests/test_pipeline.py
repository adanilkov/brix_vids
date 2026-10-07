import unittest
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PIL import Image,ImageFont
from video_pipeline.alignment import align,match_transcript
from video_pipeline.captions import display_words,groups_for
from video_pipeline.common import ROOT,digest,fingerprint,load_json,resolve_time,save_json,validate_words
from video_pipeline.graphics import font_path,make_brand_overlay
from video_pipeline.planning import plan_shots
from video_pipeline.render import artifact_paths,prepare

def words(text):
    return [{'word':s,'start':i*.3,'end':(i+1)*.3,'probability':.99} for i,s in enumerate(text.split())]

class AlignmentTests(unittest.TestCase):
    def test_imported_timings_survive_audio_move_but_reject_changed_contents(self):
        with TemporaryDirectory() as tmp:
            folder=Path(tmp);source=folder/'old'/'audio.mp3';source.parent.mkdir()
            source.write_bytes(b'roofing voiceover')
            moved=folder/'roofing'/'audio.mp3';moved.parent.mkdir()
            transcript=folder/'transcript.txt';transcript.write_text('hello world')
            timings=folder/'timings.json';save_json(timings,words('hello world'))
            cache=folder/'cache'
            binding=cache/'alignment-bindings'/f'{digest(str(timings))}.json'
            save_json(binding,{'audio':fingerprint(source),'timings':fingerprint(timings)})
            source.rename(moved)
            job={'audio':str(moved),'transcript':str(transcript),'alignment':{'words':str(timings)}}
            project=folder/'project';project.mkdir()
            with patch('video_pipeline.alignment.CACHE',cache):
                self.assertEqual(len(align(job,1,project)),2)
                self.assertIn('sha256',load_json(binding)['audio'])
                stat=moved.stat()
                moved.write_bytes(b'Xoofing voiceover')
                os.utime(moved,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                with self.assertRaisesRegex(ValueError,'Audio or imported timings changed'):
                    align(job,1,project)

    def test_hyphenated_words_and_hallucinated_tail(self):
        raw=words('No long -term contract. Free. Free.')
        raw[-1]['probability']=.01
        matched,issues=match_transcript(raw,'No long-term contract. Free.')
        self.assertEqual([w['word'] for w in matched],['No','long-term','contract.','Free.'])
        self.assertAlmostEqual(matched[1]['end'],.9)
        self.assertEqual(issues[0]['kind'],'removed_low_confidence_trailing_words')

    def test_wrong_spoken_price_requires_review(self):
        matched,issues=match_transcript(words('For five dollars monthly'),'For three dollars monthly')
        self.assertIsNone(matched)
        self.assertTrue(any(i['kind']=='estimated_timing' for i in issues))

    def test_high_confidence_extra_words_are_not_discarded(self):
        matched,_=match_transcript(words('Completely free plus tax'),'Completely free')
        self.assertIsNone(matched)

    def test_equivalent_currency_formats_preserve_price_and_span(self):
        matched,issues=match_transcript(words('For $297 monthly'),'For two hundred ninety-seven dollars monthly')
        self.assertIsNotNone(matched)
        displayed=display_words(matched,[])
        self.assertEqual([w['word'] for w in displayed],['For','$297','monthly'])
        self.assertEqual((displayed[1]['start'],displayed[1]['end']),(.3,.6))
        self.assertEqual(issues[0]['kind'],'equivalent_number_format')

    def test_different_numeric_price_is_not_treated_as_equivalent(self):
        matched,_=match_transcript(words('For $597 monthly'),'For two hundred ninety-seven dollars monthly')
        self.assertIsNone(matched)

    def test_audio_change_cannot_leave_timing_outside_recording(self):
        with self.assertRaises(ValueError):validate_words(words('a longer script'),.5)

    def test_anchors_follow_voiceover_and_reject_ambiguity(self):
        w=words('No paid ads no hidden fees')
        self.assertAlmostEqual(resolve_time({'phrase':'hidden fees','offset':-.1},w,3),1.1)
        with self.assertRaisesRegex(ValueError,'Ambiguous'):resolve_time({'phrase':'no'},w,3)
        self.assertAlmostEqual(resolve_time({'phrase':'no','occurrence':1},w,3),.9)

class CaptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brand=load_json(ROOT/'video_pipeline/brands/brix/brand.json')
        cls.brand['_directory']=str(ROOT/'video_pipeline/brands/brix')

    def test_currency_preserves_full_spoken_time_range(self):
        w=words('For two hundred ninety-seven dollars monthly')
        result=display_words(w,[{'spoken':'two hundred ninety-seven dollars','display':'$297'}])
        self.assertEqual([t['word'] for t in result],['For','$297','monthly'])
        self.assertEqual((result[1]['start'],result[1]['end']),(.3,1.5))

    def test_real_script_fits_safe_width_and_keeps_every_word(self):
        original=load_json(ROOT/'video_pipeline/alignments/roof_1.words.json')
        groups=groups_for(original,font_path(self.brand,'caption'),self.brand['captions'])
        self.assertEqual([w['word'] for g in groups for w in g['words']],[w['word'] for w in original])
        font=ImageFont.truetype(str(font_path(self.brand,'caption')),self.brand['captions']['size'])
        for group in groups:
            self.assertLessEqual(len(group['lines']),2)
            self.assertLessEqual(max(font.getlength(' '.join(line)) for line in group['lines']),840)
            self.assertGreater(group['end'],group['start'])

    def test_sentence_boundary_is_not_crossed_for_short_phrase(self):
        groups=groups_for(words('Every job. So that when someone calls.'),font_path(self.brand,'caption'),self.brand['captions'])
        self.assertEqual(groups[0]['text'],'Every job.')

class HeaderTests(unittest.TestCase):
    def setUp(self):
        self.brand=load_json(ROOT/'video_pipeline/brands/brix/brand.json')
        self.brand['_directory']=str(ROOT/'video_pipeline/brands/brix')

    def test_niche_variants_fit_centered_without_covering_content(self):
        with TemporaryDirectory() as tmp:
            project=Path(tmp)
            for niche in ('roofers','plumbers','general contractors'):
                with self.subTest(niche=niche):
                    make_brand_overlay(self.brand,project,{'niche':niche})
                    layout=load_json(project/'header_layout.json')
                    self.assertEqual(layout['headline']['lines'],[f'{niche.upper()}:','RANK #1 ON GOOGLE LOCALY'])
                    bounds=layout['headline']['line_bounds']
                    for left,top,right,bottom in bounds:
                        self.assertAlmostEqual((left+right)/2,540,delta=.5)
                        self.assertGreaterEqual(left,72)
                        self.assertLessEqual(right,1008)
                        self.assertGreater(top,layout['visible_bounds'][3])
                        self.assertLessEqual(bottom,layout['bar_bounds'][3])
                    with Image.open(project/'brand_header.png') as image:
                        self.assertEqual(image.getpixel((0,0)),(0,0,0,255))
                        height=self.brand['layout']['header']['height']
                        self.assertEqual(image.size,(1080,self.brand['video']['height']))
                        self.assertEqual(image.getchannel('A').crop((0,0,1080,height)).getextrema(),(255,255))
                        self.assertIsNone(image.getchannel('A').crop((0,height,1080,image.height)).getbbox())

    def test_missing_niche_cannot_silently_reuse_roofers(self):
        with TemporaryDirectory() as tmp:
            for niche in (None,'   '):
                with self.assertRaisesRegex(ValueError,'--niche'):
                    make_brand_overlay(self.brand,Path(tmp),{'niche':niche})

    def test_unreadably_long_niche_is_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'shorter --niche'):
                make_brand_overlay(self.brand,Path(tmp),{'niche':'a very long business category '*8})

class OutputLayoutTests(unittest.TestCase):
    def test_output_outside_shared_output_directory_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'output/<video>/output/'):
            artifact_paths({'id':'outside','output':'outside/output/outside.mp4'})

    def test_prepare_keeps_finished_output_separate_from_preview_and_work_files(self):
        job=load_json(ROOT/'video_pipeline/jobs/roof_1/A_original.json')
        job.pop('artifact_version',None)
        (ROOT/'output').mkdir(exist_ok=True)
        with TemporaryDirectory(dir=ROOT/'output') as tmp:
            video=Path(tmp)
            job['output']=str(video/'output'/'another_video.mp4')
            job_file=Path(tmp)/'job.json';job_file.write_text(json.dumps(job))
            full=prepare(job_file)
            preview=prepare(job_file,preview=True)
            self.assertEqual(full['project'],video/'project')
            self.assertEqual(full['storyboard'],video/'storyboard'/'another_video.jpg')
            self.assertEqual(full['captions'],video/'captions'/'another_video.srt')
            self.assertEqual(preview['project'],video/'preview'/'project')
            self.assertEqual(preview['output'],video/'preview'/'output'/'another_video_preview.mp4')
            self.assertTrue((full['project']/'graphics.ass').is_file())
            self.assertTrue((preview['project']/'graphics.ass').is_file())
            self.assertEqual(list((video/'output').iterdir()),[])

class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.catalog={'clips':[{'id':str(i),'file':f'clip{i}.mp4','crop_center':[.5,.5],'source_in':1,'framing':'wide' if i%2 else 'close'} for i in range(4)]}
        self.info={'duration':20,'has_video':True,'width':1920,'height':1080,'rotation':0}
        self.p1=patch('video_pipeline.planning.load_json',return_value=self.catalog);self.p1.start();self.addCleanup(self.p1.stop)
        self.p2=patch('video_pipeline.planning.probe',return_value=self.info);self.p2.start();self.addCleanup(self.p2.stop)

    def test_source_overrun_rejected(self):
        job={'id':'x','catalog':'catalog.json','shots':[{'clip':'0','start':0,'end':4,'source_in':18}]}
        with self.assertRaisesRegex(ValueError,'exceeds source'):plan_shots(job,words('hello there'),4,30)

    def test_gap_rejected(self):
        job={'id':'x','catalog':'catalog.json','shots':[{'clip':'0','start':0,'end':1},{'clip':'1','start':1.1,'end':3}]}
        with self.assertRaisesRegex(ValueError,'gap'):plan_shots(job,words('hello there'),3,30)

    def test_automatic_plan_repeatable_complete_and_no_adjacent_repeats(self):
        job={'id':'automatic','catalog':'catalog.json','shot_selection':{'seconds_per_shot':3,'seed':4}}
        w=words('A new website. Better local visibility. More opportunities to show your work.')
        first=plan_shots(job,w,12.2,30);second=plan_shots(job,w,12.2,30)
        self.assertEqual(first,second)
        self.assertEqual(sum(s['frames'] for s in first),366)
        self.assertTrue(all(a['clip']!=b['clip'] for a,b in zip(first,first[1:])))
        self.assertGreaterEqual(len({s['clip'] for s in first}),3)

if __name__=='__main__':unittest.main()
