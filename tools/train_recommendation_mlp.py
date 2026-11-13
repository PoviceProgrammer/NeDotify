"""Train and export a ranker from prepared, chronological impression pairs."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

if __name__ == '__main__':
    sys.path[0] = str(Path(__file__).resolve().parents[1])

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from services.recommendation_mlp import (FEATURE_SCHEMA_VERSION, LAYER_NORM_EPSILON, LAYERS,
                                         PROJECTION_SIZE, SCALAR_FEATURES, RecommendationMLP)


class Ranker(nn.Module):
    def __init__(self, architecture, mean, scale):
        super().__init__()
        self.architecture = architecture
        sizes = LAYERS[architecture]
        self.projection = nn.Linear(512, PROJECTION_SIZE)
        self.layers = nn.ModuleList(nn.Linear(a, b) for a, b in zip(sizes[:-1], sizes[1:], strict=True))
        self.dropout = nn.Dropout(.25)
        self.register_buffer('scalar_mean', torch.from_numpy(mean))
        self.register_buffer('scalar_scale', torch.from_numpy(scale))

    def forward(self, audio, scalars, present):
        audio_present = torch.linalg.vector_norm(audio, dim=-1, keepdim=True) > 1e-12
        projected = self.projection(audio)
        norms = torch.linalg.vector_norm(projected, dim=-1, keepdim=True)
        projected = torch.where(audio_present & (norms > 1e-12), projected / norms.clamp_min(1e-12), 0)
        interaction = projected[:, 0] * projected[:, 2]
        interaction = F.layer_norm(interaction, (PROJECTION_SIZE,), eps=LAYER_NORM_EPSILON).clamp(-4, 4)
        scalars = torch.where(present, (scalars - self.scalar_mean) / self.scalar_scale, 0)
        features = torch.cat((projected.flatten(1) * PROJECTION_SIZE ** .5, interaction, scalars, present), dim=1)
        for layer in self.layers[:-1]:
            features = self.dropout(F.relu(layer(features)))
        return self.layers[-1](features)[:, 0]

    def export_arrays(self):
        arrays = {name: getattr(self, name).detach().cpu().numpy() for name in ('scalar_mean', 'scalar_scale')}
        modules = [('projection', self.projection), *((f'layer{i}', layer) for i, layer in enumerate(self.layers))]
        for name, layer in modules:
            arrays[f'{name}_weight'] = layer.weight.detach().cpu().numpy().T
            arrays[f'{name}_bias'] = layer.bias.detach().cpu().numpy()
        return arrays


def read_pairs(path, catalog_version):
    with np.load(path, allow_pickle=False) as data:
        if (data['feature_schema_version'].item() != FEATURE_SCHEMA_VERSION
                or data['catalog_version'].item() != catalog_version
                or data['scalar_features'].tolist() != list(SCALAR_FEATURES)):
            raise ValueError(f'Incompatible training split: {path}')
        audio = np.asarray(data['audio'], dtype=np.float32)
        scalars = np.asarray(data['scalars'], dtype=np.float32)
        present = np.asarray(data['present'])
        minutes = np.asarray(data['evaluation_timestamp_min'])
    count = len(audio)
    if (count == 0 or audio.shape != (count, 2, 3, 512) or scalars.shape != (count, 2, 16)
            or present.shape != scalars.shape or present.dtype != np.bool_
            or minutes.shape != (count,) or not np.issubdtype(minutes.dtype, np.integer)
            or not np.isfinite(audio).all() or not np.isfinite(scalars[present]).all()):
        raise ValueError(f'Invalid impression-pair arrays: {path}')
    return audio, np.where(present, scalars, 0), present, minutes


def scalar_statistics(scalars, present):
    count = present.sum(axis=(0, 1)).clip(min=1)
    mean = scalars.sum(axis=(0, 1), dtype=np.float64) / count
    centered = np.where(present, scalars - mean, 0)
    scale = np.sqrt((centered * centered).sum(axis=(0, 1)) / count)
    scale[scale < 1e-6] = 1
    return mean.astype(np.float32), scale.astype(np.float32)


def pair_differences(model, batch):
    audio, scalars, present = batch
    scores = model(audio.flatten(0, 1), scalars.flatten(0, 1), present.flatten(0, 1)).reshape(-1, 2)
    return scores[:, 0] - scores[:, 1]


def train(args):
    torch.manual_seed(args.seed)
    training = read_pairs(args.train, args.catalog_version)
    validation = read_pairs(args.validation, args.catalog_version)
    if training[3].max() >= validation[3].min():
        raise ValueError('Validation must begin strictly after training')
    model = Ranker(args.architecture, *scalar_statistics(training[1], training[2]))
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
    train_tensors = tuple(torch.from_numpy(array) for array in training[:3])
    validation_tensors = tuple(torch.from_numpy(array) for array in validation[:3])
    batches = torch.utils.data.DataLoader(torch.utils.data.TensorDataset(*train_tensors), batch_size=128, shuffle=True)
    validation_batches = torch.utils.data.DataLoader(torch.utils.data.TensorDataset(*validation_tensors), batch_size=128)
    best, best_loss, stale = None, float('inf'), 0
    for epoch in range(args.epochs):
        model.train()
        for batch in batches:
            optimizer.zero_grad()
            loss = F.softplus(-pair_differences(model, batch)).mean()
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.inference_mode():
            diffs = torch.cat([pair_differences(model, batch) for batch in validation_batches])
            val_loss = float(F.softplus(-diffs).mean())
        if not np.isfinite(val_loss):
            raise ValueError('Validation produced a nonfinite loss')
        print(json.dumps({'epoch': epoch + 1, 'pair_loss': val_loss,
                          'pair_accuracy': float((diffs > 0).float().mean())}))
        if val_loss < best_loss:
            best_loss = val_loss
            best = {name: value.detach().clone() for name, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= 3:
                break
    model.load_state_dict(best)
    arrays = model.export_arrays()
    sample = tuple(t[:100].flatten(0, 1) for t in validation_tensors)
    with torch.inference_mode():
        expected = model(*sample).numpy()
    actual = RecommendationMLP(args.architecture, arrays).score_batch(*(t.numpy() for t in sample))
    np.testing.assert_allclose(actual, expected, atol=1e-5, rtol=0)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as folder:
        output = Path(folder) / 'weights.npz'
        np.savez(output, **arrays, architecture=args.architecture, catalog_version=args.catalog_version,
                 feature_schema_version=FEATURE_SCHEMA_VERSION, scalar_features=SCALAR_FEATURES)
        with output.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        os.link(output, args.output)
    print(json.dumps({'weights_sha256': digest, 'parameters': sum(p.numel() for p in model.parameters()),
                      'numpy_max_abs_error': float(np.max(np.abs(actual - expected)))}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog-version', required=True)
    parser.add_argument('--architecture', choices=tuple(LAYERS), default='compact')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if args.epochs < 1 or args.output.suffix != '.npz' or not args.catalog_version.strip():
        parser.error('Expected positive epochs, an .npz output and a catalog version')
    train(args)


if __name__ == '__main__':
    main()
