"""Shared narration normalization, music selection, and music-bed processing."""
import math,wave
import numpy as np

def choose_music(seed,profile=None):
    from .common import load_json,path,digest
    catalog=load_json(path('music/catalogs/approved.json'))
    tracks=catalog['tracks']
    if profile is None:profile=catalog.get('default')
    if profile is None:
        selected=tracks[int(digest(seed),16)%len(tracks)]
    else:
        selected=next((t for t in tracks if t['id']==profile),None)
        if selected is None:raise ValueError(f'Unknown music choice: {profile}')
    return dict(selected['music'],profile=selected['id'])

def voice_filter(measures):
    return 'highpass=f=75,loudnorm=I=-16:TP=-1.5:LRA=7:'+':'.join(
        f'{arg}={measures[key]}' for arg,key in [('measured_I','input_i'),
        ('measured_TP','input_tp'),('measured_LRA','input_lra'),
        ('measured_thresh','input_thresh'),('offset','target_offset')])+':linear=true'

def music_input(music,project,duration):
    from .common import path
    gain=float(music.get('gain',1))
    if not math.isfinite(gain) or not 0<=gain<=1:
        raise ValueError('Music gain must be between 0 and 1; 0.8 means 20% quieter.')
    mode=music.get('mode','synth')
    if mode=='none':return [],None
    if mode=='synth':
        synthesize(project/'music.wav',duration,music.get('level_db',-37),music.get('bpm',96))
        args=['-i',project/'music.wav'];filters='anull'
    elif mode=='file':
        if music.get('start',0)!=0:
            raise ValueError('Bake a nonzero music start offset into the source before a production render.')
        args=['-stream_loop','-1','-i',path(music['file'])]
        filters=(f'loudnorm=I={music.get("lufs",-34)}:TP=-6:LRA=7,'
                 f'afade=t=in:d=0.6,afade=t=out:st={max(0,duration-1.3)}:d=1.3')
    else:raise ValueError(f'Unknown music mode: {mode}')
    return args,f'{filters},volume={gain:.10g}'

def synthesize(filename,duration,level_db=-37,bpm=96):
    sr=48000;n=round(duration*sr);time=np.arange(n)/sr
    music=np.zeros((n,2),dtype=np.float64)
    beat=60/bpm;bar=4*beat
    chords=[(47,54,59,62,66),(43,50,55,59,62),(50,57,62,66,69),(45,52,57,61,64)]
    def add(start,sound,pan=0):
        offset=round(start*sr);count=min(len(sound),n-offset)
        if count<=0:return
        music[offset:offset+count,0]+=sound[:count]*math.sqrt((1-pan)/2)
        music[offset:offset+count,1]+=sound[:count]*math.sqrt((1+pan)/2)
    def hz(m):return 440*2**((m-69)/12)
    for i,start in enumerate(np.arange(0,duration,bar)):
        chord=chords[i%4];length=bar+.5;t=np.arange(round(length*sr))/sr
        envelope=np.minimum(t/.35,1)*np.minimum((length-t)/.6,1)
        pad=sum(np.sin(2*np.pi*hz(m)*t+j*.32)*(.06 if j else .09) for j,m in enumerate(chord))
        add(start,pad*envelope*.35,(-.22 if i%2 else .22))
        for j in range(8):
            t=np.arange(round(.9*sr))/sr;frequency=hz(chord[[2,3,4,3,2,3,1,3][j]]+12)
            tone=(np.sin(2*np.pi*frequency*t)+.18*np.sin(4*np.pi*frequency*t))*np.exp(-t*6.4)*np.minimum(t/.012,1)
            add(start+j*beat/2,tone*.05,.3 if j%2 else -.3)
        for j in (0,2):
            t=np.arange(round(.18*sr))/sr
            kick=np.sin(2*np.pi*(52*t+2.8*(1-np.exp(-t*18))))*np.exp(-t*25)*np.minimum(t/.008,1)
            add(start+j*beat,kick*.07)
    music*=(np.minimum(time,1)*np.minimum((duration-time)/1.4,1))[:,None]
    music*=10**(level_db/20)/max(1e-9,np.sqrt(np.mean(music**2)))
    with wave.open(str(filename),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(sr)
        out.writeframes((np.clip(music,-.95,.95)*32767).astype('<i2').tobytes())
