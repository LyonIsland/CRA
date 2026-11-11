"""Offline contract and training smoke tests; never a physical-success test."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import torch
from camera_policy import CONTRACT, MANUAL_CONTRACT, HISTORY, CameraNetwork, CameraPolicy, image_tensor,goal_tensor
from camera_runtime import CommandIntegrator, save_episode
from train_camera_policy import Episodes, split_paths, train


class CameraOnlyChecks(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.rgb = np.random.default_rng(1).integers(0, 256, (48, 64, 3), dtype=np.uint8)

    def test_no_state_or_channel_identity(self):
        self.assertTrue(torch.equal(image_tensor(self.rgb), image_tensor(self.rgb[:, :, [2, 0, 1]])))
        for bad in [np.zeros(45), {'rgb': self.rgb, 'pose': [0, 0, 0]}, self.rgb.astype(float)]:
            with self.assertRaises(ValueError):image_tensor(bad)

    def test_bounded_actuator_without_robot_feedback(self):
        actuator = CommandIntegrator(np.zeros(7), [[-.02, .02]]*7)
        for _ in range(50):result = actuator.step(np.ones(7))
        self.assertTrue(np.allclose(result, .02))
        before = actuator.target.copy()
        for bad in [np.zeros(4), np.full(7, np.nan), np.full(7, 2.)]:
            with self.assertRaises(ValueError):actuator.step(bad)
            self.assertTrue(np.array_equal(before, actuator.target))

    def test_train_split_and_realtime_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Synthetic fixtures exercise code paths; these are NOT robot demos.
            for ep, group in enumerate(['layout-a', 'layout-a', 'layout-b']):
                frames = [np.full_like(self.rgb, 30+ep*60), np.full_like(self.rgb, 40+ep*60)]
                save_episode(root/f'{ep}.npz', frames, self.rgb, [np.zeros(7)]*2, group)
            paths = sorted(root.glob('*.npz'))
            left, right = split_paths(paths, 42)
            self.assertEqual((paths[0] in left), (paths[1] in left))
            self.assertFalse(set(left) & set(right))
            dataset = Episodes(paths)
            self.assertEqual(dataset[2][0].shape, (HISTORY, 1, 96, 128))
            self.assertTrue(torch.equal(dataset[2][0][0], dataset[2][0][-1]))
            self.assertFalse(torch.equal(dataset[1][0][-1], dataset[2][0][0]))
            report = train(root, root/'model.pt', epochs=1, batch_size=2)
            self.assertFalse(report['physical_success_evaluated'])
            policy = CameraPolicy(root/'model.pt', self.rgb)
            action = policy(self.rgb)
            self.assertEqual(action.shape, (7,))
            self.assertTrue(np.isfinite(action).all() and np.abs(action).max() <= 1)
            with self.assertRaises(TypeError):policy(self.rgb, object_pose=[0, 0, 0])
            policy.reset()
            self.assertTrue(np.allclose(action, policy(self.rgb)))
            torch.save({'model': CameraNetwork().state_dict()}, root/'legacy.pt')
            with self.assertRaises(ValueError):CameraPolicy(root/'legacy.pt', self.rgb)
            with self.assertRaises(FileExistsError):
                save_episode(paths[0], [self.rgb], self.rgb, [np.zeros(7)], 'a')

    def test_reject_privileged_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.npz'
            np.savez(path, contract=CONTRACT, rgb=np.stack([self.rgb]), goal_rgb=self.rgb,
                     actions=np.zeros((1, 7)), split_group='a', object_pose=np.zeros(3))
            with self.assertRaises(ValueError):Episodes([path])

    def test_manual_pages_masked_training_and_checkpoint_contract(self):
        from train_camera_policy import collate
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for ep,count in enumerate([2,3]):
                pages=np.stack([np.full_like(self.rgb,50+i*30) for i in range(count)])
                save_episode(root/f'{ep}.npz',[self.rgb]*2,pages,[np.zeros(7)]*2,f'layout-{ep}',manual=True)
            data=Episodes(sorted(root.glob('*.npz')))
            frames,goals,actions,mask=collate([data[0],data[2]])
            model=CameraNetwork().eval()
            with torch.inference_mode():
                padded=model(frames,goals,mask)
                alone=model(frames[:1],goals[:1,:2])
            self.assertTrue(torch.allclose(padded[:1],alone,atol=1e-6))
            report=train(root,root/'manual.pt',epochs=1,batch_size=2)
            self.assertEqual(report['contract'],MANUAL_CONTRACT)
            policy=CameraPolicy(root/'manual.pt',[self.rgb,self.rgb],manual=True)
            self.assertEqual(policy(self.rgb).shape,(7,))
            with self.assertRaises(ValueError):CameraPolicy(root/'manual.pt',self.rgb)


if __name__ == '__main__':
    unittest.main()
