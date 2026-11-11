"""Offline boundary checks. Synthetic images here are NEVER real training data."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import torch
from camera_explore import Explorer,EXPLORATION_CONTRACT
from camera_policy import CameraPolicy
from pretrain_camera import Transitions,VisualMotorModel,train,test_checkpoint


class PretrainChecks(unittest.TestCase):
    def test_forward_prediction_cannot_read_target_frame(self):
        torch.set_num_threads(2)
        model=VisualMotorModel().eval()
        before=torch.rand(2,1,96,128);action=torch.rand(2,7)
        with torch.inference_mode():
            first=model(before,torch.zeros_like(before),action)[1]
            second=model(before,torch.ones_like(before),action)[1]
        self.assertTrue(torch.equal(first,second))

    def make_data(self,root,group,**extra):
        path=root/(group+'.npz')
        rng=np.random.default_rng(sum(group.encode()))
        np.savez_compressed(path,contract=EXPLORATION_CONTRACT,
            rgb=rng.integers(0,256,(4,24,32,3),dtype=np.uint8),
            actions=rng.uniform(-1,1,(3,7)).astype(np.float32),split_group=group,**extra)
        return path

    def test_command_only_exploration_bound(self):
        explorer=Explorer(12)
        actions=np.stack([explorer.action() for _ in range(5000)])
        commands=actions.cumsum(0)
        self.assertLessEqual(np.abs(actions).max(),1.)
        self.assertLessEqual(np.abs(commands[:,:6]).max(),18.0001)
        self.assertGreaterEqual(commands[:,6].min(),-25.0001)
        self.assertLessEqual(commands[:,6].max(),.0001)
        self.assertGreater(actions.std(),.1)

    def test_reject_privileged_fields_and_bad_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=self.make_data(root,'a',object_pose=np.zeros(3))
            with self.assertRaises(ValueError):Transitions([path])
            np.savez(path,contract=EXPLORATION_CONTRACT,rgb=np.zeros((3,4,4,3),dtype=np.uint8),
                     actions=np.zeros((3,7)),split_group='a')
            with self.assertRaises(ValueError):Transitions([path])

    def test_group_separation_checkpoint_resume_and_no_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            a,b,c=[self.make_data(root,g) for g in ('a','b','c')]
            with self.assertRaises(ValueError):train([a],[a],root/'bad',epochs=1)
            with np.load(a) as original:
                renamed={k:original[k] for k in original.files}
            renamed['split_group']='different-label'
            np.savez(root/'renamed.npz',**renamed)
            with self.assertRaises(ValueError):train([a],[root/'renamed.npz'],root/'bad-duplicate',epochs=1)
            report=train([a],[b],root/'run',epochs=1,batch_size=2)
            self.assertFalse(report['deployable_policy'])
            self.assertFalse(report['physical_success_evaluated'])
            for path in (root/'run/best.pt',root/'run/encoder.pt'):
                with self.assertRaises(ValueError):CameraPolicy(path,np.zeros((24,32,3),dtype=np.uint8),manual=True)
            train([a],[b],root/'resumed',epochs=1,batch_size=2,resume=root/'run/best.pt')
            with self.assertRaises(ValueError):test_checkpoint(root/'run/best.pt',[b],root/'bad-test.json')
            test_checkpoint(root/'run/best.pt',[c],root/'test.json')


if __name__=='__main__':unittest.main()
