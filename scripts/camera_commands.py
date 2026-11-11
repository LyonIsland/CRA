"""Shared validation for human commands; no scene or policy dependencies."""
import numpy as np


def validate_command(command):
    if not isinstance(command,dict) or command.get('op') not in {'step','pause','start_policy','record','save','shutdown'}:
        raise ValueError('Unsupported camera-only session command')
    if set(command)!=({'op','action'} if command['op']=='step' else {'op'}):
        raise ValueError('Unexpected command fields; scene data is not accepted')
    if command['op']=='step':
        action=np.asarray(command.get('action'),dtype=float)
        if action.shape!=(7,) or not np.isfinite(action).all() or np.abs(action).max()>1:
            raise ValueError('Expected seven bounded joint/gripper increments')
    return command
