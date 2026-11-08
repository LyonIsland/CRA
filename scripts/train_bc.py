"""Train on a separate CUDA-enabled Python; export portable inference weights."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
import torch
from torch import nn

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', default='outputs/demonstrations.npz')
    p.add_argument('--out', default='outputs/policy')
    p.add_argument('--epochs', type=int, default=300)
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()
    torch.manual_seed(args.seed)
    torch.set_num_threads(4)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    data = np.load(args.data)
    obs, actions = data['observations'].astype(np.float32), data['actions'].astype(np.float32)
    ids = data['episode_ids']
    episodes = np.unique(ids)
    rng = np.random.default_rng(args.seed)
    rng.shuffle(episodes)
    val_ids = episodes[:max(1, len(episodes)//5)]
    train = ~np.isin(ids, val_ids)
    if not train.any():
        raise ValueError('Need at least two demonstration episodes')
    mean = obs[train].mean(0)
    std = np.maximum(obs[train].std(0), .01)
    x = torch.tensor((obs - mean) / std, device=device)
    y = torch.tensor(actions, device=device)
    ti = torch.tensor(np.flatnonzero(train), device=device)
    vi = torch.tensor(np.flatnonzero(~train), device=device)
    model = nn.Sequential(nn.Linear(obs.shape[1],256), nn.ReLU(),
                          nn.Linear(256,256), nn.ReLU(),
                          nn.Linear(256,256), nn.ReLU(), nn.Linear(256,4)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=.0004)
    best = float('inf')
    start = time.perf_counter()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        model.train()
        order = ti[torch.randperm(len(ti), device=device)]
        for batch in order.split(1024):
            pred = model(x[batch])
            loss = (pred - y[batch]).square().mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            val = (model(x[vi]) - y[vi]).square().mean().item()
        if val < best:
            best = val
            weights = {'mean': mean, 'std': std}
            for i, layer in enumerate([model[0],model[2],model[4],model[6]]):
                weights[f'w{i}'] = layer.weight.detach().cpu().numpy().copy()
                weights[f'b{i}'] = layer.bias.detach().cpu().numpy().copy()
            np.savez(args.out + '.npz', **weights)
            torch.save(model.state_dict(), args.out + '.pt')
        if (epoch+1) % 25 == 0:
            print(json.dumps({'epoch':epoch+1,'validation_mse':val,'best_mse':best}),flush=True)
    result = {'method':'behavior_cloning', 'device':device,
              'gpu':torch.cuda.get_device_name(0) if device=='cuda' else None,
              'torch':torch.__version__, 'cuda':torch.version.cuda,
              'samples':len(obs), 'episodes':len(episodes),
              'train_episodes':len(episodes)-len(val_ids),
              'validation_episodes':len(val_ids), 'best_validation_mse':best,
              'epochs':args.epochs, 'seed':args.seed,
              'elapsed_seconds':time.perf_counter()-start}
    Path(args.out+'.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)

if __name__ == '__main__':
    main()
