"""Windows 설치본 / Linux 소스 설치 패키지. 개인 데이터 제외."""
import argparse
from datetime import datetime
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
VERSION = '1.1.0'
MODEL = ROOT / 'models' / 'gemma-2-2b-it-Q4_K_M.gguf'

def source_files():
    for path in sorted(ROOT.iterdir()):
        if path.is_file() and (path.suffix in ('.py', '.md', '.sh', '.bat', '.iss', '.spec', '.vbs') or path.name in ('requirements.txt', '.gitignore', '.gitattributes', 'run_app')):
            yield path
    for folder in ('docs', 'tests'):
        for path in sorted((ROOT / folder).rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.md') and '__pycache__' not in path.parts:
                yield path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=('windows', 'linux', 'all'), default='windows')
    parser.add_argument('--exe-only', action='store_true')
    args = parser.parse_args()
    if args.platform in ('windows', 'all') and sys.platform != 'win32':
        parser.error('Windows EXE 빌드는 Windows에서 실행하세요.')
    release = ROOT / 'installer_output' / f'{VERSION}-{datetime.now():%Y%m%d-%H%M%S}'
    release.mkdir(parents=True, exist_ok=False)
    if args.platform in ('windows', 'all'):
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
                        '--name=WelfareAI', '--collect-all=llama_cpp',
                        '--distpath', str(release / 'dist'), '--workpath', str(release / 'work'),
                        '--specpath', str(release), str(ROOT / 'app.py')], cwd=ROOT, check=True)
        app_dir = release / 'dist' / 'WelfareAI'
        if MODEL.exists():
            (app_dir / 'models').mkdir(exist_ok=True)
            shutil.copy2(MODEL, app_dir / 'models' / MODEL.name)
        shutil.copytree(ROOT / 'docs', app_dir / 'docs')
        if not args.exe_only:
            candidates = [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Inno Setup 6/ISCC.exe',
                          Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe')]
            compiler = next((p for p in candidates if p.is_file()), None)
            if compiler is None:
                raise RuntimeError(f'Inno Setup 6이 필요합니다. 실행 폴더: {app_dir}')
            subprocess.run([str(compiler), f'/DBuildDir={app_dir}', f'/DReleaseDir={release}',
                            str(ROOT / 'setup.iss')], check=True, cwd=ROOT)
    if args.platform in ('linux', 'all'):
        archive = release / f'WelfareAI-linux-{VERSION}.tar.gz'
        with tarfile.open(archive, 'w:gz', compresslevel=1) as bundle:
            for path in source_files():
                info = bundle.gettarinfo(str(path), f'WelfareAI/{path.relative_to(ROOT).as_posix()}')
                if path.suffix == '.sh' or path.name == 'run_app':
                    info.mode = 0o755
                with path.open('rb') as stream:
                    bundle.addfile(info, stream)
            if MODEL.exists():
                bundle.add(MODEL, arcname=f'WelfareAI/models/{MODEL.name}')
        print(f'Linux 소스 설치 패키지: {archive}', flush=True)
    print(f'배포 결과: {release}', flush=True)

if __name__ == '__main__':
    main()
