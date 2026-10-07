import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import av
import numpy as np
from video_pipeline.audio import choose_music,music_input,synthesize
from video_pipeline.common import ROOT,load_json
from video_pipeline.media import ffmpeg
from video_pipeline.remix import verify_audio_only
from video_pipeline.render import artifact_paths,prepare
from video_pipeline.common import save_json,content_fingerprint


class MusicTests(unittest.TestCase):
    def test_twenty_percent_reduction_survives_music_normalization(self):
        with TemporaryDirectory() as tmp:
            project=Path(tmp)
            source=project/'source.wav';synthesize(source,3,level_db=-20)
            for mode in ('synth','file'):
                rendered=[]
                for gain in (1,.8):
                    spec={'mode':mode,'file':str(source),'gain':gain,'lufs':-30}
                    args,filters=music_input(spec,project,3)
                    output=project/f'{mode}_{gain}.wav'
                    ffmpeg([*args,'-af',filters,'-t',3,'-ar',48000,'-c:a','pcm_f32le',output])
                    with av.open(str(output)) as f:
                        rendered.append(np.concatenate([a.to_ndarray().ravel() for a in f.decode(audio=0)]))
                ratio=np.sqrt(np.mean(rendered[1]**2)/np.mean(rendered[0]**2))
                self.assertAlmostEqual(ratio,.8,places=4)

    def test_remix_rejects_visual_or_narration_changes_and_original_overwrite(self):
        source=load_json(ROOT/'video_pipeline/jobs/roof_2/A_original.json')
        target=copy.deepcopy(source)
        target.update(id='roof_2_music_test',output='output/roof_2_music_test/output/roof_2_music_test.mp4',music=choose_music('x','relaxed_groove'))
        verify_audio_only(target,source)
        for field,value in [('niche','plumbers'),('audio','voiceover/roofing/roof_3_audio.mp3')]:
            changed=dict(target,**{field:value})
            with self.assertRaisesRegex(ValueError,'only id, output, and music'):
                verify_audio_only(changed,source)
        with self.assertRaisesRegex(ValueError,'distinct output'):
            verify_audio_only(dict(target,output=source['output']),source)

    def test_new_jobs_default_to_option_two_and_keep_original_available(self):
        choices=[choose_music(f'ad_{i}') for i in range(16)]
        self.assertEqual({c['profile'] for c in choices},{'relaxed_groove'})
        self.assertTrue(all(c['gain']==.8 for c in choices))
        self.assertEqual(choose_music('ad','original')['profile'],'original')
        self.assertEqual(choose_music('roof_7'),choose_music('roof_7'))

    def test_same_folder_remix_preserves_source_project_during_prepare(self):
        source=load_json(ROOT/'video_pipeline/jobs/roof_2/A_original.json')
        source.pop('artifact_version',None)
        with TemporaryDirectory(dir=ROOT/'output') as tmp:
            video=Path(tmp)
            source['output']=str(video/'output/source.mp4')
            source_file=video/'source_job.json';save_json(source_file,source)
            initial=prepare(source_file)
            before={p:content_fingerprint(p) for p in initial['project'].rglob('*') if p.is_file()}
            target=dict(source,id='roof_2_curiosity',output=str(video/'output/source_curiosity.mp4'),music=choose_music('ad'))
            with self.assertRaisesRegex(ValueError,'artifact_version'):
                verify_audio_only(target,source)
            target['artifact_version']='curiosity'
            verify_audio_only(target,source)
            target_file=video/'target_job.json';save_json(target_file,target)
            revised=prepare(target_file)
            self.assertEqual(revised['output'].parent,initial['output'].parent)
            self.assertEqual(revised['project'],initial['project']/'curiosity')
            for filename,original in before.items():
                self.assertEqual(content_fingerprint(filename),original)

    def test_artifact_version_cannot_escape_project_directory(self):
        job=load_json(ROOT/'video_pipeline/jobs/roof_2/A_original.json')
        for version in ('../output','/tmp','',123):
            with self.assertRaisesRegex(ValueError,'artifact_version'):
                artifact_paths(dict(job,artifact_version=version))
