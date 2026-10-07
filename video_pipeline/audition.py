"""Quick music comparisons using an existing edit and its original narration."""
import html
import math
import re
from pathlib import Path
from .common import ROOT, content_fingerprint, load_json, path, save_json
from .media import ffmpeg, loudness, probe
from .quality import check_export
from .render import artifact_paths
from .geometry import canvas_size


def validate_catalog(catalog, duration):
    if not math.isfinite(duration) or not 3 <= duration <= 30:
        raise ValueError('Choose a preview duration between 3 and 30 seconds.')
    identifiers = [catalog.get('id', '')]
    tracks = catalog.get('tracks', [])
    if not 1 <= len(tracks) <= 8:
        raise ValueError('Choose between one and eight music tracks.')
    identifiers += [t.get('id', '') for t in tracks]
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in identifiers):
        raise ValueError('Catalog and track IDs must use letters, numbers, underscores, or hyphens.')
    if len(set(identifiers[1:])) != len(tracks) or '00_current' in identifiers[1:]:
        raise ValueError('Track IDs must be unique; 00_current is reserved.')
    for track in tracks:
        music = track['music']
        start = float(music.get('start', 0))
        level = float(music.get('lufs', -31))
        if music.get('mode') != 'file' or not math.isfinite(start) or start < 0:
            raise ValueError('Each audition track needs file music and a nonnegative start time.')
        if not math.isfinite(level) or not -40 <= level <= -24:
            raise ValueError('Keep audition background music between -40 and -24 LUFS.')
        gain=float(music.get('gain',1))
        if not math.isfinite(gain) or not 0<=gain<=1:
            raise ValueError('Music gain must be between 0 and 1.')


def review_page(output, tracks, duration):
    cards = []
    for index, track in enumerate(tracks):
        ident = html.escape(track['id'], quote=True)
        label = html.escape(track['label'])
        title = html.escape(track.get('title', 'Original synthesized bed'))
        artist = html.escape(track.get('artist', 'Brix'))
        description = html.escape(track.get('description', 'The existing approved mix.'))
        solo = (f'<button class="solo" data-audio="../audio/{ident}.mp3">Hear music alone</button>'
                if index else '')
        cards.append(f'<article><span class="number">{index}</span><div><h2>{label}</h2>'
                     f'<p>{description}</p><small>{title} · {artist}</small><div class="actions">'
                     f'<button class="choose" data-video="../output/{ident}.mp4" '
                     f'data-label="{html.escape(track["label"], quote=True)}">Play with ad</button>{solo}'
                     f'</div></div></article>')
    template = (ROOT/'video_pipeline/templates/music_review.html').read_text(encoding='utf-8')
    output.write_text(template.replace('<!-- CARDS -->', '\n'.join(cards)).replace('{{DURATION}}', f'{duration:g}'), encoding='utf-8')


def audition(job_file, catalog_file, duration=12):
    job = load_json(path(job_file))
    catalog = load_json(path(catalog_file))
    validate_catalog(catalog, duration)
    original = artifact_paths(job)['output']
    if not original.is_file():
        raise ValueError('Render this job first; music auditions reuse its finished visuals.')
    before = content_fingerprint(original)
    info = probe(original)
    width,height=canvas_size({'video':info},preview=True)
    fps = info['fps']
    duration = round(duration * fps) / fps
    if duration > min(info['duration'], probe(path(job['audio']))['duration']):
        raise ValueError('The audition must fit within both the finished edit and narration.')
    for track in catalog['tracks']:
        music = track['music']
        source = probe(path(music['file']))
        if not source['has_audio'] or music.get('start', 0) + duration > source['duration']:
            raise ValueError(f'The selected excerpt exceeds the music source: {track["id"]}')

    root = original.parent.parent/'preview'/catalog['id']
    for folder in ('output', 'project', 'audio', 'review'):
        (root/folder).mkdir(parents=True, exist_ok=True)
    project = root/'project'
    visuals = project/'visuals.mp4'
    ffmpeg(['-i', original, '-t', duration, '-an', '-vf', f'scale={width}:{height}',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-threads', '3',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', visuals], project/'visuals.log')
    measures = loudness(path(job['audio']), True)
    norm = 'highpass=f=75,loudnorm=I=-16:TP=-1.5:LRA=7:' + ':'.join(
        f'{arg}={measures[key]}' for arg, key in [('measured_I', 'input_i'),
        ('measured_TP', 'input_tp'), ('measured_LRA', 'input_lra'),
        ('measured_thresh', 'input_thresh'), ('offset', 'target_offset')]) + ':linear=true'
    voice = project/'voice.wav'
    ffmpeg(['-i', path(job['audio']), '-af', norm, '-t', duration,
            '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s24le', voice], project/'voice.log')
    tracks = [{'id': '00_current', 'label': 'Current music'}] + catalog['tracks']
    reports = {}
    for track in tracks:
        ident = track['id']
        work = project/ident
        work.mkdir(exist_ok=True)
        partial = work/'preview.partial.mp4'
        args = ['-i', visuals]
        if ident == '00_current':
            args += ['-i', original, '-map', '0:v:0', '-map', '1:a:0']
        else:
            music = track['music']
            start = music.get('start', 0)
            # Match perceived music level across songs; keep narration identical.
            music_filter = (f'loudnorm=I={music.get("lufs", -31)}:TP=-6:LRA=7,'
                            f'atrim=duration={duration},asetpts=PTS-STARTPTS,'
                            f'afade=t=in:d=0.3,afade=t=out:st={duration-.4}:d=0.4,'
                            f'volume={music.get("gain",1)},aresample=48000,aformat=channel_layouts=stereo')
            bed = work/'music.wav'
            ffmpeg(['-ss', start, '-i', path(music['file']), '-af', music_filter,
                    '-t', duration, '-c:a', 'pcm_s24le', bed], work/'music.log')
            args += ['-i', voice, '-i', bed, '-filter_complex',
                     '[1:a][2:a]amix=inputs=2:duration=first:normalize=0,'
                     'alimiter=limit=0.94:level=false[a]', '-map', '0:v:0', '-map', '[a]']
            ffmpeg(['-i', bed, '-af', 'loudnorm=I=-18:TP=-2:LRA=7', '-ar', '48000',
                    '-c:a', 'libmp3lame', '-b:a', '192k', root/'audio'/f'{ident}.mp3'], work/'solo.log')
        args += ['-t', duration, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                 '-ar', '48000', '-ac', '2', '-movflags', '+faststart', partial]
        ffmpeg(args, work/'mix.log')
        reports[ident] = check_export(partial, work, duration, width, height, fps)
        partial.replace(root/'output'/f'{ident}.mp4')
        print(f'Ready: {track["label"]}', flush=True)
    if content_fingerprint(original) != before:
        raise ValueError('The source export changed during the audition.')
    save_json(project/'audition.json', {'job': str(path(job_file)), 'source': str(original),
              'source_fingerprint': before, 'duration': duration, 'catalog': catalog,
              'quality_reports': reports, 'production_jobs_changed': False})
    page = root/'review/index.html'
    review_page(page, tracks, duration)
    print(f'Compare music: {page}', flush=True)
    return page
