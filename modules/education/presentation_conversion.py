"""Local, isolated LibreOffice conversion for static presentation previews."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

PRESENTATION_SUFFIXES = {'.ppt', '.pptx', '.pps', '.ppsx', '.pptm', '.ppsm', '.odp', '.ppx'}


def find_libreoffice():
    for root in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if root:
            path = Path(root) / 'LibreOffice/program/soffice.com'
            if path.is_file():
                return str(path)
    return shutil.which('soffice.com') or shutil.which('soffice')


def presentation_pdf(source, cache_root):
    source = Path(source)
    if source.stat().st_size > 512 * 1024 * 1024:
        raise ValueError('The presentation is too large for inline conversion. Open it externally.')
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / (digest.hexdigest() + '.pdf')
    if target.is_file():
        return str(target)
    executable = find_libreoffice()
    if not executable:
        raise ValueError('Install LibreOffice on this computer to preview PowerPoint slides here, or use Open in External Application.')
    suffix = source.suffix.lower()
    if suffix == '.ppx':
        if not zipfile.is_zipfile(source):
            raise ValueError('The PPX file is not a recognized PowerPoint presentation.')
        with zipfile.ZipFile(source) as archive:
            if 'ppt/presentation.xml' not in archive.namelist():
                raise ValueError('The PPX file is not a recognized PowerPoint presentation.')
        suffix = '.pptx'
    with tempfile.TemporaryDirectory(prefix='conversion-', dir=cache_root) as tmp:
        work = Path(tmp)
        staged = work / ('slides' + suffix)
        shutil.copyfile(source, staged)
        profile = work / 'profile'
        (profile / 'user').mkdir(parents=True)
        (profile / 'user/registrymodifications.xcu').write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding='utf-8')
        command = [executable, '-env:UserInstallation=' + profile.as_uri(), '--headless',
                   '--nologo', '--nodefault', '--norestore', '--convert-to',
                   'pdf:impress_pdf_Export', '--outdir', str(work), str(staged)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags)
        try:
            code = process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            else:
                process.kill()
            process.wait()
            raise ValueError('Presentation conversion timed out. Open the original file externally.') from None
        pdf = work / 'slides.pdf'
        if code != 0 or not pdf.is_file():
            raise ValueError('This presentation could not be converted. It may be damaged, encrypted or unsupported. Open the original file externally.')
        with pdf.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise ValueError('The presentation converter did not produce a valid PDF.')
        # Unique conversion folders allow concurrent requests without partial cache files.
        os.replace(pdf, target)
    return str(target)
