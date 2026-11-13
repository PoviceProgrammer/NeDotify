"""Encode a manifest of locally available, licensed recordings with OpenL3."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Import from the repository root without shadowing PyPI's packaging with
# tools/packaging when TensorFlow imports it.
if __name__ == '__main__':
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from services.embedding_catalog import ENCODER


def extract_vector(path, model):
    import numpy as np
    import openl3
    import soundfile as sf

    with sf.SoundFile(path) as audio:
        sample_rate = audio.samplerate
        if not audio.frames:
            raise ValueError(f'Empty recording: {path.name}')
        window = sample_rate * 10
        if audio.frames <= 3 * window:
            excerpts = [audio.read(dtype='float32', always_2d=True).mean(axis=1)]
        else:
            excerpts = []
            for position in (0.2, 0.5, 0.8):
                audio.seek(max(0, min(audio.frames - window, int(audio.frames * position) - window // 2)))
                excerpts.append(audio.read(window, dtype='float32', always_2d=True).mean(axis=1))
        duration = audio.frames / sample_rate
    frames, _ = openl3.get_audio_embedding(excerpts, sample_rate, model=model, frontend='librosa',
                                            input_repr='mel128', embedding_size=512,
                                            center=False, hop_size=1, verbose=0)
    vector = np.concatenate(frames).mean(axis=0)
    norm = np.linalg.norm(vector)
    if vector.shape != (512,) or not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError(f'Invalid embedding for {path.name}')
    return (vector / norm).astype(np.float16), duration


def build(input_path, output_path, version):
    import numpy as np
    import openl3

    tracks = json.loads(input_path.read_text(encoding='utf-8'))
    if not isinstance(tracks, list) or not tracks or not all(isinstance(track, dict) for track in tracks):
        raise ValueError('Expected a nonempty JSON list of recordings')
    if output_path.exists() or output_path.with_suffix('.npy').exists():
        raise FileExistsError('Use a new output name for each catalog version')
    model = openl3.models.load_audio_embedding_model('mel128', 'music', 512, frontend='librosa')
    entries, vectors, seen = [], [], set()
    for track in tracks:
        fields = ('recording_id', 'title', 'artist', 'audio_file', 'audio_license', 'attribution')
        if any(not isinstance(track.get(field), str) or not track[field].strip() for field in fields):
            raise ValueError('Recording metadata, local audio and license attribution are required')
        if track['recording_id'] in seen:
            raise ValueError('Duplicate recording ID')
        seen.add(track['recording_id'])
        path = input_path.parent / track['audio_file']
        vector, duration = extract_vector(path, model)
        entry = {key: track[key] for key in ('recording_id', 'title', 'artist', 'mbid', 'isrc', 'language', 'release_year',
                                             'audio_license', 'attribution') if key in track}
        entry.update(duration=duration, vector_index=len(vectors))
        entries.append(entry)
        vectors.append(vector)

    with tempfile.TemporaryDirectory(dir=output_path.parent) as folder:
        vector_path = Path(folder) / 'vectors.npy'
        np.save(vector_path, np.stack(vectors), allow_pickle=False)
        with vector_path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        manifest = dict(encoder=ENCODER, version=version, vectors_sha256=digest, tracks=entries,
                        preprocessing='openl3-0.4.2/librosa/mono/3x10s/1s-hop/mean/l2-v1')
        manifest_path = Path(folder) / 'catalog.json'
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        # Publish the manifest last. Hard links avoid overwriting a concurrent
        # build and keep a failed publication from leaving a usable manifest.
        published_vectors = output_path.with_suffix('.npy')
        os.link(vector_path, published_vectors)
        try:
            os.link(manifest_path, output_path)
        except OSError:
            published_vectors.unlink()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recordings', type=Path)
    parser.add_argument('catalog', type=Path)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if args.catalog.suffix != '.json' or not args.version.strip():
        parser.error('Provide a .json catalog path and a nonempty version')
    build(args.recordings, args.catalog, args.version)


if __name__ == '__main__':
    main()
