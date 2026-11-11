"""Shorter observation routes with the same complete set of viewpoints."""
from itertools import permutations
import numpy as np

def route_length(start,poses):
    points=np.vstack([start,poses])
    return float(np.linalg.norm(np.diff(points,axis=0),axis=1).sum())

def order_viewpoints(start,poses):
    if not poses:return [],0.,0.
    original=route_length(start,poses)
    ordered=list(min(permutations(poses),key=lambda route:route_length(start,route)))
    return ordered,original,route_length(start,ordered)
