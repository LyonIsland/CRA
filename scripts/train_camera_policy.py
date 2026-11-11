"""Train only camera/action episodes; never consume legacy state demonstrations."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from camera_policy import CONTRACT, MANUAL_CONTRACT, HISTORY, CameraNetwork, image_tensor, goal_tensor


class Episodes(Dataset):
    def __init__(self, paths):
        self.episodes = []
        self.index = []
        self.contracts = set()
        for path in paths:
            with np.load(path, allow_pickle=False) as data:
                if set(data.files) != {'contract', 'rgb', 'goal_rgb', 'actions', 'split_group'}:
                    raise ValueError(f'{path}: unexpected inputs; state datasets are forbidden')
                contract=str(data['contract'])
                if contract not in (CONTRACT, MANUAL_CONTRACT):
                    raise ValueError(f'{path}: incompatible observation contract')
                rgb, goal, actions = data['rgb'], data['goal_rgb'], data['actions'].copy()
                if rgb.ndim != 4 or len(rgb) != len(actions) or not len(rgb):
                    raise ValueError(f'{path}: unaligned or empty episode')
                if actions.shape != (len(rgb), 7) or not np.isfinite(actions).all() or np.abs(actions).max() > 1:
                    raise ValueError(f'{path}: expected seven normalized commands')
                frames = torch.stack([image_tensor(frame) for frame in rgb])
                self.contracts.add(contract)
                target = goal_tensor(goal)
                ep = len(self.episodes)
                self.episodes.append((frames, target, torch.tensor(actions, dtype=torch.float32)))
                self.index.extend((ep, t) for t in range(len(rgb)))

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        ep, t = self.index[index]
        frames, goal, actions = self.episodes[ep]
        history = frames[[max(0, i) for i in range(t-HISTORY+1, t+1)]]
        return history, goal, actions[t]


def collate(batch):
    frames, goals, actions=zip(*batch)
    count=max(len(goal) for goal in goals)
    padded=torch.zeros(len(batch),count,*goals[0].shape[1:])
    mask=torch.zeros(len(batch),count,dtype=torch.bool)
    for i,goal in enumerate(goals):
        padded[i,:len(goal)]=goal
        mask[i,:len(goal)]=True
    return torch.stack(frames),padded,torch.stack(actions),mask


def split_paths(paths, seed):
    groups = {}
    for path in paths:
        with np.load(path, allow_pickle=False) as data:
            group = str(data['split_group'])
            if not group:
                raise ValueError('Each episode needs a layout/task split_group')
            groups.setdefault(group, []).append(path)
    keys = sorted(groups)
    if len(keys) < 2:
        raise ValueError('Need at least two independent layout/task groups')
    np.random.default_rng(seed).shuffle(keys)
    validation = set(keys[:max(1, len(keys)//5)])
    return ([p for k in keys if k not in validation for p in groups[k]],
            [p for k in keys if k in validation for p in groups[k]])


def train(data_dir, out, epochs=50, seed=42, batch_size=32, encoder_init=None):
    if epochs < 1 or batch_size < 1:
        raise ValueError('epochs and batch_size must be positive')
    torch.manual_seed(seed)
    torch.set_num_threads(4)
    paths = sorted(Path(data_dir).glob('*.npz'))
    train_paths, val_paths = split_paths(paths, seed)
    training, validation = Episodes(train_paths), Episodes(val_paths)
    contracts=training.contracts|validation.contracts
    if len(contracts)!=1:raise ValueError('Do not mix photograph and instruction-page datasets in one run')
    contract=next(iter(contracts))
    loader = DataLoader(training, batch_size=batch_size, shuffle=True,collate_fn=collate)
    val_loader = DataLoader(validation, batch_size=batch_size,collate_fn=collate)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = CameraNetwork().to(device)
    if encoder_init:
        payload=torch.load(encoder_init,map_location='cpu',weights_only=True)
        if payload.get('contract')!='camera_visual_motor_pretrain_v1' or payload.get('deployable_policy') is not False:
            raise ValueError('Expected an isolated visual pretraining encoder')
        model.encoder.load_state_dict(payload['encoder'],strict=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
    best = float('inf')
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(epochs):
        model.train()
        for frames, goal, action, mask in loader:
            frames, goal, action = frames.to(device), goal.to(device), action.to(device)
            # Independent exposure jitter: fixed brightness must not label a part.
            frames = (frames * torch.empty(len(frames), 1, 1, 1, 1, device=device).uniform_(.65, 1.35)).clamp(0, 1)
            goal = (goal * torch.empty(len(goal), 1, 1, 1, 1, device=device).uniform_(.65, 1.35)).clamp(0, 1)
            loss = torch.nn.functional.smooth_l1_loss(model(frames, goal,mask.to(device)), action)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizer.step()
        model.eval()
        total = 0.
        with torch.inference_mode():
            for frames, goal, action, mask in val_loader:
                total += torch.nn.functional.mse_loss(model(frames.to(device), goal.to(device),mask.to(device)), action.to(device), reduction='sum').item()
        mse = total / (len(validation)*7)
        if mse < best:
            best = mse
            torch.save({'contract': contract, 'history': HISTORY,
                        'model': {k: v.detach().cpu() for k, v in model.state_dict().items()}}, out)
        print(json.dumps({'epoch': epoch+1, 'validation_action_mse': mse}), flush=True)
    report = {'contract': contract, 'device': device, 'best_validation_action_mse': best,
              'train_episodes': [p.name for p in train_paths], 'validation_episodes': [p.name for p in val_paths],
              'dataset_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              'physical_success_evaluated': False, 'epochs': epochs, 'seed': seed,
              'encoder_init_sha256':hashlib.sha256(Path(encoder_init).read_bytes()).hexdigest() if encoder_init else None}
    out.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--out', default='outputs/camera_only/policy.pt')
    parser.add_argument('--epochs', type=int, default=50)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--encoder-init',type=Path,help='Visual pretraining encoder; still requires successful demonstrations')
    args = parser.parse_args()
    train(args.data, args.out, args.epochs, args.seed,encoder_init=args.encoder_init)
