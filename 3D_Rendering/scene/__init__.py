#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use 
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#

import os
import random
import json
from utils.system_utils import searchForMaxIteration
from scene.dataset_readers import sceneLoadTypeCallbacks
from scene.gaussian_model import GaussianModel
from arguments import ModelParams
from utils.camera_utils import cameraList_from_camInfos, camera_to_JSON

class Scene:

    gaussians : GaussianModel

    def __init__(self, args : ModelParams, gaussians : GaussianModel, load_iteration=None, shuffle=True, resolution_scales=[1.0]):
        """b
        :param path: Path to colmap scene main folder.
        """
        self.model_path = args.model_path
        self.loaded_iter = None
        self.gaussians = gaussians

        if load_iteration:
            if load_iteration == -1:
                self.loaded_iter = searchForMaxIteration(os.path.join(self.model_path, "point_cloud"))
            else:
                self.loaded_iter = load_iteration
            print("Loading trained model at iteration {}".format(self.loaded_iter))

        self.train_cameras = {}
        self.test_cameras = {}

        if os.path.exists(os.path.join(args.source_path, "sparse")):
            scene_info = sceneLoadTypeCallbacks["Colmap"](args.source_path, args.images, args.depths, args.eval, args.train_test_exp, args.detected_results)
        elif os.path.exists(os.path.join(args.source_path, "transforms_train.json")):
            print("Found transforms_train.json file, assuming Blender data set!")
            scene_info = sceneLoadTypeCallbacks["Blender"](args.source_path, args.white_background, args.depths, args.eval)
        else:
            assert False, "Could not recognize scene type!"

        if not self.loaded_iter:
            with open(scene_info.ply_path, 'rb') as src_file, open(os.path.join(self.model_path, "input.ply") , 'wb') as dest_file:
                dest_file.write(src_file.read())
            json_cams = []
            camlist = []
            if scene_info.test_cameras:
                camlist.extend(scene_info.test_cameras)
            if scene_info.train_cameras:
                camlist.extend(scene_info.train_cameras)
            for id, cam in enumerate(camlist):
                json_cams.append(camera_to_JSON(id, cam))
            with open(os.path.join(self.model_path, "cameras.json"), 'w') as file:
                json.dump(json_cams, file)

        if shuffle:
            random.shuffle(scene_info.train_cameras)  # Multi-res consistent random shuffling
            random.shuffle(scene_info.test_cameras)  # Multi-res consistent random shuffling

        self.cameras_extent = scene_info.nerf_normalization["radius"]

        for resolution_scale in resolution_scales:
            print("Loading Training Cameras")
            self.train_cameras[resolution_scale] = cameraList_from_camInfos(scene_info.train_cameras, resolution_scale, args, scene_info.is_nerf_synthetic, False)
            print("Loading Test Cameras")
            self.test_cameras[resolution_scale] = cameraList_from_camInfos(scene_info.test_cameras, resolution_scale, args, scene_info.is_nerf_synthetic, True)

        if self.loaded_iter:
            self.gaussians.load_ply(os.path.join(self.model_path,
                                                           "point_cloud",
                                                           "iteration_" + str(self.loaded_iter),
                                                           "point_cloud.ply"), args.train_test_exp)
        else:
            self.gaussians.create_from_pcd(scene_info.point_cloud, scene_info.train_cameras, self.cameras_extent)

    def save(self, iteration):
        point_cloud_path = os.path.join(self.model_path, "point_cloud/iteration_{}".format(iteration))
        self.gaussians.save_ply(os.path.join(point_cloud_path, "point_cloud.ply"))
        exposure_dict = {
            image_name: self.gaussians.get_exposure_from_name(image_name).detach().cpu().numpy().tolist()
            for image_name in self.gaussians.exposure_mapping
        }

        with open(os.path.join(self.model_path, "exposure.json"), "w") as f:
            json.dump(exposure_dict, f, indent=2)

    def save_marked_image(self, point_cloud_path = None):
        if point_cloud_path is None:
            point_cloud_path = os.path.join(self.model_path, "point_cloud/marked")
            # 경로가 없으면 생성
            os.makedirs(point_cloud_path, exist_ok=True)
        else:
            # marked  Point_cloud는 따로 path를 할당
            point_cloud_path = os.path.join(point_cloud_path, self.model_path[-10:])
            os.makedirs(point_cloud_path, exist_ok=True)
        self.gaussians.save_ply(os.path.join(point_cloud_path, "marked_point_cloud.ply"))

    def getTrainCameras(self, scale=1.0):
        return self.train_cameras[scale]

    def getTestCameras(self, scale=1.0):
        return self.test_cameras[scale]
    
    def save_numpy_img(self, image, path):
        from PIL import Image
        import numpy as np
        image = (image * 255).astype(np.uint8)
        image = Image.fromarray(image)
        image.save(path)

    def mark_crack_points(self, cam_list, pipe, detection_model, novel=False):
        for cam in cam_list:
            if float(cam.cracked_points[0]['probability']) < 0.7:
                mask = self.gaussians.mark_crack_points(cam)
                if mask.sum() != 0:
                    if novel:
                        novelview_image = self.gaussians.novelViewRenderer(cam, mask, pipe)

                        # Saving novel view image
                        path = f"/home/dannypk99/Desktop/Gaussian_Splatting/gaussian-splatting/novel_view_image/building/novelview_image_{cam.image_name[:-4]}.jpg"
                        # path = f"/home/dannypk99/Desktop/Gaussian_Splatting/gaussian-splatting/novel_view_image/stairs/novelview_image_{cam.image_name[:-4]}"
                        self.save_numpy_img(novelview_image, f"{path}.jpg")
                        new_prob = 0 if detection_model(f"{path}.jpg")[0].boxes.conf.numel() == 0 else detection_model(f"{path}.jpg")[0].boxes.conf[0]

                        if new_prob > 0.7:
                            self.gaussians.mark_crack_points(cam, modify=True, color='R')
                        else:
                            print("Crack dismissed...")
                    else:
                        self.gaussians.mark_crack_points(cam, modify=True, color='R')
            else:
                self.gaussians.mark_crack_points(cam, modify=True, color='R')


