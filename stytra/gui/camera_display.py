from PyQt5.QtCore import QTimer, Qt, QRectF, QObject, QPoint
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton
import pyqtgraph as pg
from queue import Empty
import numpy as np
from paramqt import ParameterGui
from stytra.tracking.diagnostics import draw_fish_angles_ls


class CameraViewWidget(QWidget):
    def __init__(self, camera_queue, control_queue=None, camera_rotation=0,
                 camera_parameters=None, update_timer=None):
        """
        A widget to show the camera and display the controls
        :param camera_queue: queue dispatching frames to display
        :param control_queue: queue with controls for the camera
        :param camera_rotation:
        """

        super().__init__()
        self.camera_display_widget = pg.GraphicsLayoutWidget()

        self.display_area = pg.ViewBox(lockAspect=1, invertY=False)
        self.camera_display_widget.addItem(self.display_area)

        self.display_area.setRange(QRectF(0, 0, 640, 640), update=True,
                                   disableAutoRange=True)
        self.image_item = pg.ImageItem()
        self.image_item.setImage(np.zeros((640, 480), dtype=np.uint8))
        self.display_area.addItem(self.image_item)

        self.camera_queue = camera_queue
        self.control_queue = control_queue
        self.camera_rotation = camera_rotation
        self.update_timer = update_timer
        self.update_timer.timeout.connect(self.update_image)
        self.centre = np.array([0, 0])

        self.layout = QVBoxLayout()

        self.layout.addWidget(self.camera_display_widget)
        if control_queue is not None:
            self.camera_parameters = camera_parameters
            self.control_widget = ParameterGui(self.camera_parameters)
            self.layout.addWidget(self.control_widget)
            for control in self.control_widget.parameter_controls:
                control.control_widget.valueChanged.connect(self.update_controls)
            self.control_queue = control_queue
            self.control_queue.put(self.camera_parameters.get_param_dict())

        self.captureButton = QPushButton('Capture frame')
        self.captureButton.clicked.connect(self.save_image)
        self.layout.addWidget(self.captureButton)

        self.setLayout(self.layout)

    def update_controls(self):
        self.control_widget.save_meta()
        self.control_queue.put(self.camera_parameters.get_param_dict())

    def modify_frame(self, frame):
        return frame

    def update_image(self):
        im_in = None
        first = True
        while True:
            try:
                if first:
                    time, im_in = self.camera_queue.get(timeout=0.001)
                    first = False
                else:
                    _, _ = self.camera_queue.get(timeout=0.001)

                if self.camera_rotation >= 1:
                    im_in = np.rot90(im_in, k=self.camera_rotation)

                self.centre = np.array(im_in.shape[::-1])/2

            except Empty:
                break
        if im_in is not None:
            #print('get frame!')
            self.image_item.setImage(self.modify_frame(im_in))

    def save_image(self):
        pass
        # TODO write saving


class CameraTailSelection(CameraViewWidget):
    def __init__(self, tail_start_points_queue, tail_position_data, roi_dict=None,
                 tracking_params=None,
                 *args, **kwargs):
        """Widget for select tail points and monitoring tracking in embedded animal.
        :param tail_start_points_queue: queue where to dispatch tail points
        :param tail_position_data: DataAccumulator object with tail tracking data.
        :param roi_dict: dictionary for setting default tail position
        """
        self.tail_position_data = tail_position_data
        super().__init__(*args, **kwargs)
        self.tail_start_points_queue = tail_start_points_queue
        self.tracking_params = tracking_params

        self.label = pg.TextItem('Select tail of the fish:')

        if not roi_dict:  # use input dictionary
            roi_dict = {'start_y': 242, 'start_x': 413,
                        'tail_length_y': 0, 'tail_length_x': -190}
        self.roi_dict = roi_dict

        # Draw ROI for tail selection:
        self.roi_tail = pg.LineSegmentROI(((self.roi_dict['start_y'], self.roi_dict['start_x']),
                                           (self.roi_dict['start_y'] + self.roi_dict['tail_length_y'],
                                            self.roi_dict['start_x'] + self.roi_dict['tail_length_x'])),
                                          pen=None)

        self.tail_curve = pg.PlotCurveItem(pen=dict(color=(230, 40, 5), width=3))
        self.display_area.addItem(self.tail_curve)
        self.display_area.addItem(self.roi_tail)

        self.get_tracking_params()
        self.tail_start_points_queue.put(self.get_tracking_params())
        self.roi_tail.sigRegionChangeFinished.connect(self.send_roi_to_queue)

    def reset_ROI(self):
        # TODO figure out how to load handles
        pass
        # self.roi_tail.setPoints(((self.roi_dict['start_y'], self.roi_dict['start_x']),
        #                                    (self.roi_dict['start_y'] + self.roi_dict['tail_length_y'],
        #                                     self.roi_dict['start_x'] + self.roi_dict['tail_length_x'])))

    def send_roi_to_queue(self):
        self.tail_start_points_queue.put(self.get_tracking_params())

    def get_tracking_params(self):
        # Invert x and y:
        handle_pos = self.roi_tail.getSceneHandlePositions()
        try:
            p1 = self.display_area.mapSceneToView(handle_pos[0][1])
            p2 = self.display_area.mapSceneToView(handle_pos[1][1])
            self.roi_dict['start_y'] = p1.x()
            self.roi_dict['start_x'] = p1.y()  # start x
            self.roi_dict['tail_length_y'] = p2.x() - p1.x()  # delta y
            self.roi_dict['tail_length_x'] = p2.y() - p1.y()  # delta x

            self.tracking_params.update(self.roi_dict)

        except np.linalg.LinAlgError:
            print('not init')
        return self.tracking_params

    def update_image(self):
        super().update_image()
        if len(self.tail_position_data.stored_data) > 1:
            angles = self.tail_position_data.stored_data[-1][2:]
            start_x = self.roi_dict['start_x']
            start_y = self.roi_dict['start_y']
            tail_len_x = self.roi_dict['tail_length_x']
            tail_len_y = self.roi_dict['tail_length_y']
            tail_length = np.sqrt(tail_len_x ** 2 + tail_len_y ** 2)
            # Get segment length:
            tail_segment_length = tail_length / (len(angles) - 1)
            points = [np.array([start_x, start_y])]
            for angle in angles:
                points.append(points[-1] + tail_segment_length * np.array(
                    [np.sin(angle), np.cos(angle)]))
            points = np.array(points)
            self.tail_curve.setData(x=points[:, 1], y=points[:, 0])


class CameraViewCalib(CameraViewWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.points_calib = pg.ScatterPlotItem()
        self.display_area.addItem(self.points_calib)

    def show_calibration(self, calibrator):
        if calibrator.proj_to_cam is not None:
            camera_points = np.pad(calibrator.points, ((0, 0), (0, 1)),
                                   mode='constant', constant_values=1) @ calibrator.proj_to_cam.T

            points_dicts = []
            for point in camera_points:
                xn, yn = point[::-1]
                points_dicts.append(dict(x=xn, y=yn, size=8, brush=(210, 10, 10)))

            self.points_calib.setData(points_dicts)


if __name__ == '__main__':
    from multiprocessing import Queue
    from PyQt5.QtWidgets import QApplication
    app = QApplication([])
    q = Queue()
    for i in range(100):
        q.put(np.random.randint(0, 255, (640, 480), dtype=np.uint8))

    w = CameraTailSelection(q, 'b')
    w.show()
    app.exec_()
