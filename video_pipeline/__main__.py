from pathlib import Path
import argparse,json,sys
from .common import ROOT,CACHE,load_json,path,save_json

def new_job(args):
    from .audio import choose_music
    if not args.id.replace('_','').replace('-','').isalnum():raise ValueError('Use a simple name containing letters, numbers, underscores, or hyphens.')
    if not args.niche.strip():raise ValueError('Pass a non-empty --niche label, for example --niche roofers.')
    output=path(args.job or f'video_pipeline/jobs/{args.id}.json')
    if output.exists():raise ValueError(f'Job already exists: {output}')
    category=Path(args.audio).parent.name
    catalog=args.catalog or f'video_pipeline/catalogs/{category}.json'
    for item in (args.audio,args.transcript):
        if not path(item).is_file():raise ValueError(f'Missing input: {item}')
    if not path(catalog).is_file():
        raise ValueError(f'Missing footage catalog for {category}: {catalog}. Create it or pass --catalog.')
    creative={'cta':{'start':{'end_offset':-5.8},'lines':['Get found.','Get more calls.'],
                     'prompt':'Tap to learn more'}}
    if args.hook:
        creative['hook']={'end':3.5,'lines':args.hook.split('|')}
    job={'id':args.id,'niche':' '.join(args.niche.split()),'brand':'video_pipeline/brands/brix/brand.json','audio':args.audio,'transcript':args.transcript,
         'catalog':catalog,'output':f'output/{args.id}/output/{args.id}.mp4','end_hold':1.03,
         'alignment':{'model':'base.en','prompt':'Brix Strategies. Google Business Profile.'},
         'shot_selection':{'seconds_per_shot':3.2,'seed':args.id},'music':choose_music(args.id,args.music),
         'creative':creative}
    save_json(output,job)
    print(f'Created {output}\nEdit the creative copy in this JSON, then run: ./video.sh render {output.relative_to(ROOT) if output.is_relative_to(ROOT) else output} --preview')

def main():
    parser=argparse.ArgumentParser(description='Brix video production: one brand, reusable jobs, local renders.')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('render','batch'):
        p=sub.add_parser(name,help='Render one or more JSON jobs; stop on error with render, continue with batch.')
        p.add_argument('jobs',nargs='+');p.add_argument('--preview',action='store_true');p.add_argument('--force',action='store_true')
        p.add_argument('--workers',type=int,default=3,choices=range(1,5))
        p.add_argument('--niche',help='Override the top-banner audience for this run (otherwise read from each job).')
    p=sub.add_parser('prepare',help='Create captions, graphics, and timeline without encoding video.')
    p.add_argument('job')
    p.add_argument('--storyboard',action='store_true',help='Render representative styled frames for crop and copy review before a full encode.')
    p.add_argument('--niche',help='Override the top-banner audience for this preparation.')
    p=sub.add_parser('audition',help='Compare music over a short excerpt of an existing finished edit.')
    p.add_argument('job');p.add_argument('--catalog',required=True)
    p.add_argument('--duration',type=float,default=12,help='Excerpt length in seconds (3 to 30).')
    p=sub.add_parser('remix',help='Replace music while copying approved video without re-encoding.')
    p.add_argument('job');p.add_argument('--source-job',required=True)
    p=sub.add_parser('pair',help='Render an A/B music pair with identical video in one ad folder.')
    p.add_argument('first');p.add_argument('second')
    p.add_argument('--workers',type=int,default=3,choices=range(1,5))
    p=sub.add_parser('new',help='Create an automatic-edit job using the shared brand and footage catalog.')
    p.add_argument('id');p.add_argument('--audio',required=True);p.add_argument('--transcript',required=True)
    p.add_argument('--niche',required=True,help='Audience label, such as roofers, plumbers, or home remodelers.')
    p.add_argument('--catalog',help='Footage catalog; defaults to the category folder under voiceover/.');p.add_argument('--job')
    p.add_argument('--hook',help='Optional opening headline, with | separating lines.')
    p.add_argument('--music',help='Approved music ID; omitted uses the catalog default (option 2, relaxed_groove).')
    sub.add_parser('doctor',help='Check fonts, logo, FFmpeg, and the local environment.')
    sub.add_parser('test',help='Run focused tests for caption alignment, safe layout, and timeline validation.')
    args=parser.parse_args()
    if args.command=='pair':
        from .remix import remix,verify_audio_only
        from .render import artifact_paths,render
        first,second=load_json(path(args.first)),load_json(path(args.second))
        verify_audio_only(second,first)
        if artifact_paths(second)['output'].exists():
            raise ValueError('The second export already exists. Remove the superseded pair before intentionally rebuilding it.')
        render(args.first,workers=args.workers)
        return remix(args.second,args.first)
    if args.command=='remix':
        from .remix import remix
        return remix(args.job,args.source_job)
    if args.command=='audition':
        from .audition import audition
        return audition(args.job,args.catalog,args.duration)
    if args.command=='new':return new_job(args)
    if args.command=='doctor':
        import imageio_ffmpeg
        from .graphics import font_info,font_path
        from .media import ffmpeg
        b=load_json(path('video_pipeline/brands/brix/brand.json'));b['_directory']=str(path('video_pipeline/brands/brix'))
        for role in b['fonts']:font_info(str(font_path(b,role)))
        if not path(b['logo']).exists():raise ValueError('Missing logo.')
        if ' ass ' not in ffmpeg(['-filters']):raise ValueError('FFmpeg does not support ASS captions.')
        print(f'Ready.\nFFmpeg: {imageio_ffmpeg.get_ffmpeg_exe()}\nCache: {CACHE}\nBrand: Brix website palette, Manrope/DM Sans, supplied logo.');return
    if args.command=='test':
        import unittest
        suite=unittest.defaultTestLoader.discover(str(ROOT/'video_pipeline/tests'))
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():raise SystemExit(1)
        return
    from .render import prepare,render
    if args.command=='prepare':
        ctx=prepare(args.job,niche=args.niche)
        if args.storyboard:
            from .review import prepared_storyboard
            print(f'Storyboard: {prepared_storyboard(ctx)}')
        print(f'Prepared {len(ctx["shots"])} shots and {len(ctx["groups"])} caption phrases in {ctx["project"]}');return
    failures=[]
    for job in args.jobs:
        try:render(job,args.preview,args.force,args.workers,niche=args.niche)
        except Exception as exc:
            if args.command!='batch':raise
            failures.append({'job':job,'error':str(exc)});print(f'FAILED {job}: {exc}',file=sys.stderr)
    if failures:
        save_json(ROOT/'video_pipeline/batch_errors.json',failures);raise SystemExit(1)

if __name__=='__main__':
    try:main()
    except (ValueError,FileNotFoundError,RuntimeError) as exc:
        print(f'Video pipeline: {exc}',file=sys.stderr);raise SystemExit(1)
