"""Run from the repository root: .venv/bin/python video/add_narration.py."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / 'video'
SEGMENTS = [
    (12, 'Start in Review. Highlight the relevant text to open a comment box. '
     'Describe what went wrong, then press Enter to save your note.'),
    (7, 'Next, open Taxonomy. Related comments appear in groups, '
     'making recurring failure patterns easier to see.'),
    (10, 'Finally, review Agent suggestions. Check the highlighted evidence and '
     'proposed failure group. Select a candidate, then accept or reject it '
     'after reviewing the conversation.'),
]


def run(args):
    subprocess.run(args, check=True)


def main():
    settings = {**dotenv_values(ROOT / '.env'), **os.environ}
    missing = [k for k in ('ELEVENLABS_API_KEY', 'ELEVENLABS_VOICE_ID') if not settings.get(k)]
    if missing:
        sys.exit('Set in .env: ' + ', '.join(missing))
    pieces = []
    for index, (seconds, text) in enumerate(SEGMENTS, 1):
        audio = VIDEO / f'narration_step_{index}.mp3'
        cache = audio.with_suffix('.json')
        payload = {
            'text': text, 'model_id': 'eleven_multilingual_v2',
            'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75, 'speed': 1.0},
        }
        fingerprint = hashlib.sha256((settings['ELEVENLABS_VOICE_ID'] + json.dumps(payload)).encode()).hexdigest()
        if not (audio.exists() and cache.exists() and json.loads(cache.read_text()).get('fingerprint') == fingerprint):
            request = Request(
                'https://api.elevenlabs.io/v1/text-to-speech/'
                + quote(settings['ELEVENLABS_VOICE_ID'], safe='')
                + '?output_format=mp3_44100_128',
                data=json.dumps(payload).encode(),
                headers={'xi-api-key': settings['ELEVENLABS_API_KEY'],
                         'Content-Type': 'application/json', 'Accept': 'audio/mpeg'},
            )
            try:
                with urlopen(request, timeout=45) as response:
                    content = response.read()
                audio.write_bytes(content)
                cache.write_text(json.dumps({'fingerprint': fingerprint, 'text': text}) + '\n')
            except HTTPError as exc:
                sys.exit(f'ElevenLabs returned HTTP {exc.code}; check key permissions, voice access, and credits.')
            except URLError:
                sys.exit('Cannot reach ElevenLabs. Run this script with network access. Existing videos are preserved.')
        duration = float(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(audio),
        ], text=True))
        speed = max(1, duration / (seconds - 0.3))
        if speed > 1.15:
            sys.exit(f'Narration step {index} is too long. Shorten its script before retrying; no speech was clipped.')
        piece = VIDEO / f'narration_step_{index}.wav'
        run(['ffmpeg', '-y', '-v', 'error', '-i', str(audio),
             '-af', f'atempo={speed:.6f},adelay=100:all=1,apad',
             '-t', str(seconds), '-ar', '44100', '-ac', '1', str(piece)])
        pieces.append(piece)
    command = ['ffmpeg', '-y', '-v', 'error']
    for piece in pieces:
        command += ['-i', str(piece)]
    combined = VIDEO / 'review_ui_narration.mp3'
    command += ['-filter_complex', '[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]',
                '-map', '[a]', '-c:a', 'libmp3lame', '-q:a', '2', str(combined)]
    run(command)
    output = VIDEO / 'review_ui_voice.mp4'
    subtitles = (VIDEO / 'review_ui.srt').relative_to(ROOT).as_posix()
    run(['ffmpeg', '-y', '-v', 'error', '-i', str(VIDEO / 'review_ui_no_captions.mp4'),
         '-i', str(combined), '-map', '0:v:0', '-map', '1:a:0',
         '-vf', f"subtitles={subtitles}:force_style='FontName=DejaVu Sans,FontSize=18,Outline=1,Shadow=0,BorderStyle=3,BackColour=&H80000000,MarginV=14'",
         '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '192k', '-t', str(sum(s[0] for s in SEGMENTS)),
         '-movflags', '+faststart', str(output)])
    print(f'Created {output.relative_to(ROOT)}: 29 seconds, with synchronized ElevenLabs narration.')


if __name__ == '__main__':
    main()
