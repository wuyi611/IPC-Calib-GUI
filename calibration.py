import os
import cv2 as cv
import numpy as np
import glob
import xml.etree.ElementTree as ET


class CameraCalibrator(object):
    def __init__(self, image_size: tuple):
        super(CameraCalibrator, self).__init__()
        self.image_size = image_size
        self.matrix = np.zeros((3, 3), np.float32)
        self.new_camera_matrix = np.zeros((3, 3), np.float32)
        self.dist = np.zeros((1, 5), np.float32)
        self.roi = np.zeros(4, np.int32)
        self.is_calibrated = False  # 添加标记

    def load_params(self, param_file: str = 'camera_params.xml'):
        if not os.path.exists(param_file):
            return False  # 返回状态而不是直接退出

        try:
            tree = ET.parse(param_file)
            root = tree.getroot()

            mat_data = root.find('camera_matrix')
            matrix = dict()
            if mat_data:
                for data in mat_data.iter():
                    matrix[data.tag] = data.text
                for i in range(9):
                    self.matrix[i // 3][i % 3] = float(matrix['data{}'.format(i)])

            new_camera_matrix = dict()
            new_data = root.find('new_camera_matrix')
            if new_data:
                for data in new_data.iter():
                    new_camera_matrix[data.tag] = data.text
                for i in range(9):
                    self.new_camera_matrix[i // 3][i % 3] = float(new_camera_matrix['data{}'.format(i)])

            dist = dict()
            dist_data = root.find('camera_distortion')
            if dist_data:
                for data in dist_data.iter():
                    dist[data.tag] = data.text
                for i in range(5):
                    self.dist[0][i] = float(dist['data{}'.format(i)])

            roi = dict()
            roi_data = root.find('roi')
            if roi_data:
                for data in roi_data.iter():
                    roi[data.tag] = data.text
                for i in range(4):
                    self.roi[i] = int(roi['data{}'.format(i)])

            self.is_calibrated = True
            return True
        except Exception as e:
            print(f"Loading params failed: {e}")
            return False

    def save_params(self, save_path='camera_params.xml'):
        root = ET.Element('root')
        tree = ET.ElementTree(root)
        comment = ET.Element('about')
        comment.set('author', 'gui_user')
        root.append(comment)

        def add_node(name, data_source):
            node = ET.Element(name)
            root.append(node)
            for i, elem in enumerate(data_source.flatten()):
                child = ET.Element('data{}'.format(i))
                child.text = str(elem)
                node.append(child)

        add_node('camera_matrix', self.matrix)
        add_node('new_camera_matrix', self.new_camera_matrix)
        add_node('camera_distortion', self.dist)

        roi_node = ET.Element('roi')
        root.append(roi_node)
        for i, elem in enumerate(self.roi):
            child = ET.Element('data{}'.format(i))
            child.text = str(elem)
            roi_node.append(child)

        tree.write(save_path, 'UTF-8')
        print("Saved params in {}.".format(save_path))

    def cal_real_corner(self, corner_height, corner_width, square_size):
        obj_corner = np.zeros([corner_height * corner_width, 3], np.float32)
        obj_corner[:, :2] = np.mgrid[0:corner_height, 0:corner_width].T.reshape(-1, 2)
        return obj_corner * square_size

    def calibration(self, corner_height: int, corner_width: int, square_size: float, image_dir: str):
        # 修改：接受 image_dir 参数
        extensions = ['*.JPG', '*.jpg', '*.png']
        file_names = []
        for ext in extensions:
            file_names.extend(glob.glob(os.path.join(image_dir, ext)))

        if not file_names:
            print("No images found in directory.")
            return False

        objs_corner = []
        imgs_corner = []
        criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        obj_corner = self.cal_real_corner(corner_height, corner_width, square_size)

        found_count = 0
        for file_name in file_names:
            chess_img = cv.imread(file_name)
            if chess_img is None: continue
            gray = cv.cvtColor(chess_img, cv.COLOR_BGR2GRAY)
            ret, img_corners = cv.findChessboardCorners(gray, (corner_height, corner_width))
            if ret:
                objs_corner.append(obj_corner)
                img_corners = cv.cornerSubPix(gray, img_corners, (square_size // 2, square_size // 2), (-1, -1),
                                              criteria)
                imgs_corner.append(img_corners)
                found_count += 1
            else:
                print("Fail to find corners in {}.".format(file_name))

        if found_count < 1:
            return False

        ret, self.matrix, self.dist, rvecs, tveces = cv.calibrateCamera(objs_corner, imgs_corner, self.image_size, None,
                                                                        None)
        self.new_camera_matrix, roi = cv.getOptimalNewCameraMatrix(self.matrix, self.dist, self.image_size, alpha=0)
        self.roi = np.array(roi)
        self.is_calibrated = True
        return ret

    def rectify_image(self, img):
        if not self.is_calibrated:
            return img
        dst = cv.undistort(img, self.matrix, self.dist, None, self.new_camera_matrix)
        # 可选：裁剪黑边
        # x, y, w, h = self.roi
        # if w > 0 and h > 0:
        #     dst = dst[y:y + h, x:x + w]
        # dst = cv.resize(dst, (self.image_size[0], self.image_size[1]))
        return dst