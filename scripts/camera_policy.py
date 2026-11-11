"""Camera-only, goal-image-conditioned temporal behavior cloning.

No simulator, calibration, FK, object identity or state imports belong here.
The goal is a photograph supplied by the operator, not a scene-state vector.
"""
from collections import deque
import numpy as np
from PIL import Image
import torch
from torch import nn

CONTRACT = 'camera_only_goal_image_v1'
HISTORY = 4
SIZE = (128, 96)
MANUAL_CONTRACT = 'camera_only_manual_pages_v1'


def image_tensor(rgb):
    if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('Expected uint8 HWC RGB from the single camera')
    # Mean, rather than luminance weights: channel permutations are exactly
    # invariant. Materials must ALSO be randomized independently of part identity.
    gray = np.rint(rgb.astype(np.float32).mean(2)).astype(np.uint8)
    small = np.asarray(Image.fromarray(gray).resize(SIZE, Image.Resampling.BILINEAR)).copy()
    return torch.from_numpy(small).float().unsqueeze(0) / 255.


def goal_tensor(images):
    if isinstance(images, np.ndarray) and images.ndim==3:
        return image_tensor(images).unsqueeze(0)
    if not isinstance(images, (list, tuple, np.ndarray)) or not 1<=len(images)<=64:
        raise ValueError('Expected a goal photograph or 1 to 64 manual page images')
    return torch.stack([image_tensor(page) for page in images])


class CameraNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv2d(1, 16, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((3, 4)), nn.Flatten(), nn.Linear(768, 128), nn.ReLU())
        self.temporal = nn.GRU(256, 128, batch_first=True)
        self.action = nn.Sequential(nn.Linear(128, 64), nn.ReLU(), nn.Linear(64, 7), nn.Tanh())

    def forward(self, frames, goal, goal_mask=None):
        b, t, c, h, w = frames.shape
        seen = self.encoder(frames.reshape(b*t, c, h, w)).reshape(b, t, -1)
        if goal.ndim==4:goal=goal[:,None]
        pages=goal.shape[1]
        encoded=self.encoder(goal.reshape(b*pages,c,h,w)).reshape(b,pages,-1)
        # Every page is available on every decision. Attention uses image
        # features, never an externally supplied step number or completion flag.
        scores=torch.matmul(seen,encoded.transpose(1,2))/(128**.5)
        if goal_mask is not None:scores=scores.masked_fill(~goal_mask[:,None,:],float('-inf'))
        desired=torch.matmul(scores.softmax(-1),encoded)
        sequence, _ = self.temporal(torch.cat([seen, desired], dim=-1))
        return self.action(sequence[:, -1])


class CameraPolicy:
    def __init__(self, checkpoint, goal_rgb, *, manual=False):
        payload = torch.load(checkpoint, map_location='cpu', weights_only=True)
        expected=MANUAL_CONTRACT if manual else CONTRACT
        if payload.get('contract') != expected or payload.get('history') != HISTORY:
            raise ValueError('Legacy/state policy is incompatible with camera-only execution')
        self.model = CameraNetwork().eval()
        self.model.load_state_dict(payload['model'])
        self.goal = goal_tensor(goal_rgb)[None]
        self.frames = deque(maxlen=HISTORY)

    def reset(self):
        self.frames.clear()

    @torch.inference_mode()
    def __call__(self, rgb):
        frame = image_tensor(rgb)
        if not self.frames:
            self.frames.extend([frame] * HISTORY)
        else:
            self.frames.append(frame)
        action = self.model(torch.stack(list(self.frames))[None], self.goal)[0].numpy()
        if action.shape != (7,) or not np.isfinite(action).all():
            raise RuntimeError('Invalid visual action; stop execution')
        return action
