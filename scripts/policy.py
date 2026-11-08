"""Portable NumPy inference for the GPU-trained imitation policy."""
import numpy as np

class Policy:
    def __init__(self, path):
        self.weights = np.load(path)

    def __call__(self, observation):
        w = self.weights
        x = (observation - w['mean']) / w['std']
        for i in range(3):
            x = np.maximum(x @ w[f'w{i}'].T + w[f'b{i}'], 0)
        return np.clip(x @ w['w3'].T + w['b3'], -1, 1)
