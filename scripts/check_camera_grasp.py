"""Offline perception / command boundaries; physical grasp is tested in Isaac."""
import unittest
import cv2
import numpy as np
from pathlib import Path
from PIL import Image
from camera_grasp_policy import gray,detect,ObjectTracker,VisualGrasp


class Checks(unittest.TestCase):
    def image(self):
        rgb=np.full((480,640,3),140,np.uint8)
        box=cv2.boxPoints(((340.,260.),(64.,32.),25.))
        cv2.fillConvexPoly(rgb,np.rint(box).astype(np.int32),(230,200,215))
        return rgb

    def test_channel_permutation_and_no_privileged_input(self):
        rgb=self.image()
        self.assertTrue(np.array_equal(gray(rgb),gray(rgb[:,:,[2,0,1]])))
        for bad in ({'rgb':rgb,'pose':[0,0,0]},np.zeros(7),rgb.astype(float)):
            with self.assertRaises(ValueError):gray(bad)
        with self.assertRaises(TypeError):VisualGrasp()(rgb,object_pose=[0,0,0])

    def test_image_tracking_observes_subpixel_motion(self):
        rgb=self.image();first=detect(rgb)
        self.assertIsNotNone(first)
        tracker=ObjectTracker();original=tracker.observe(rgb).copy()
        for i in range(1,21):
            moved=cv2.warpAffine(rgb,np.float32([[1,0,i*1.5],[0,1,-i*.75]]),(640,480),borderValue=(140,140,140))
            feature=tracker.observe(moved)
        self.assertLess(np.linalg.norm(feature[:2]-original[:2]-[30,-15]),2.)

    def test_command_primitive_bounds_and_conservation(self):
        controller=VisualGrasp()
        delta=np.array([4,-8,3,0,5,4,-25.])
        commands=np.stack(list(controller.move(delta)))
        self.assertTrue(np.isfinite(commands).all())
        self.assertLessEqual(np.abs(commands).max(),1.)
        self.assertTrue(np.allclose(commands.sum(0),delta))

    def test_brick_does_not_merge_into_gripper_shadow(self):
        # Fixed camera regression image; pixel annotation is test-only and is
        # never supplied to the runtime detector or controller.
        rgb=np.asarray(Image.open(Path(__file__).resolve().parents[1]/'assets/tests/camera_grasp_shadow.png'))
        feature=detect(rgb,np.array([275.,278.,60.,-3.]))
        self.assertIsNotNone(feature)
        self.assertLess(np.linalg.norm(feature[:2]-[275,278]),3.)

    def test_acquire_whole_brick_between_open_fingers(self):
        rgb=np.asarray(Image.open(Path(__file__).resolve().parents[1]/'assets/tests/camera_grasp_between_fingers.png'))
        feature=detect(rgb)
        self.assertIsNotNone(feature)
        self.assertLess(np.linalg.norm(feature[:2]-[113,251]),4.)
        self.assertGreater(feature[2],60.)
        # The visible side face alone is not a valid whole-object acquisition.
        self.assertLess(abs(feature[3]),12.)


if __name__=='__main__':unittest.main()
