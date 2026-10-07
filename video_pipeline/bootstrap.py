"""Keep dependencies in the user's cache, outside the OneDrive workspace."""
from pathlib import Path
import hashlib, os, subprocess, sys, venv

root = Path(__file__).resolve().parents[1]
requirements = root/'video_pipeline/requirements.txt'
cache = Path(os.environ.get('BRIX_VIDEO_CACHE', Path.home()/'.cache/brix-video'))
environment = cache/f'python-{sys.version_info.major}.{sys.version_info.minor}'
python = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
stamp = environment/'requirements.sha256'
digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
if not python.exists():
    venv.EnvBuilder(with_pip=False).create(environment)
if not stamp.exists() or stamp.read_text() != digest:
    print('Setting up the reusable video environment (first run or dependency update)...', flush=True)
    subprocess.run([sys.executable, '-m', 'pip', '--python', str(python), 'install', '-r', str(requirements)], check=True)
    stamp.write_text(digest)
os.chdir(root)
os.execv(str(python), [str(python), '-m', 'video_pipeline', *sys.argv[1:]])
