from PyQt5.QtCore import pyqtSignal, QTimer, QObject
import datetime

from builtins import print

from stytra.stimulation.stimuli import DynamicStimulus, Pause
from stytra.collectors import Accumulator

from copy import deepcopy


class Protocol(QObject):
    """ Class that manages the stimulation protocol, includes a timer,
    updating signals etc.

    """
    name = ''
    sig_timestep = pyqtSignal(int)
    sig_stim_change = pyqtSignal(int)
    sig_protocol_started = pyqtSignal()
    sig_protocol_finished = pyqtSignal()

    def __init__(self, stimuli=None, n_repeats=1, pre_pause=0, post_pause=0,
                 experiment=None,
                 dt=1/60, log_print=True):
        super().__init__()

        self.t_start = None
        self.t_end = None
        self.completed = False
        self.t = 0

        self.stimuli = []
        if pre_pause > 0:
            self.stimuli.append(Pause(duration=pre_pause))
        for i in range(max(n_repeats, 1)):
            self.stimuli.extend(deepcopy(stimuli))
        if post_pause > 0:
            self.stimuli.append(Pause(duration=post_pause))

        self.current_stimulus = self.stimuli[0]
        for stimulus in self.stimuli:
            stimulus.initialise_external(experiment)

        self.i_current_stimulus = 0
        self.timer = QTimer()
        self.dt = dt
        self.past_stimuli_elapsed = None
        self.duration = self.get_duration()

        # Log will be a list of stimuli states
        self.log = []
        self.dynamic_log = DynamicLog(self.stimuli)
        self.log_print = log_print
        self.running = False

    def start(self):
        self.t_start = datetime.datetime.now()
        self.timer.timeout.connect(self.timestep)
        self.timer.setSingleShot(False)
        self.timer.start() # it is in milliseconds
        self.dynamic_log.starting_time = self.t_start
        self.dynamic_log.reset()
        self.log = []
        self.past_stimuli_elapsed = datetime.datetime.now()
        self.current_stimulus.started = datetime.datetime.now()
        self.sig_protocol_started.emit()
        self.running = True
        # self.sig_stim_change.emit(0) - not sure about commenting out this

    def timestep(self):
        if self.running:
            # Time from start in seconds
            self.t = (datetime.datetime.now() - self.t_start).total_seconds()
            self.current_stimulus.elapsed = (datetime.datetime.now() -
                                             self.past_stimuli_elapsed).total_seconds()
            if self.current_stimulus.elapsed > self.current_stimulus.duration:  # If stimulus time is over
                self.sig_stim_change.emit(self.i_current_stimulus)
                self.update_log()

                if self.i_current_stimulus >= len(self.stimuli) - 1:
                    self.completed = True
                    self.end()
                    self.sig_protocol_finished.emit()

                else:
                    # update the variable which keeps track when the last
                    # stimulus *should* have ended, in order to avoid
                    # drifting

                    self.past_stimuli_elapsed += datetime.timedelta(
                        seconds=self.current_stimulus.duration)
                    self.i_current_stimulus += 1
                    self.current_stimulus = self.stimuli[self.i_current_stimulus]
                    self.current_stimulus.start()

            self.sig_timestep.emit(self.i_current_stimulus)
            if isinstance(self.current_stimulus, DynamicStimulus):
                self.sig_stim_change.emit(self.i_current_stimulus)
                self.current_stimulus.update()
                self.update_dynamic_log()

    def end(self):
        if not self.completed:
            self.update_log()
        if self.running:
            self.running = False
            self.t_end = datetime.datetime.now()
            try:
                self.timer.timeout.disconnect()
                self.timer.stop()
            except:
                pass

    def update_log(self):
        """This is coming directly from the Logger class and can be made better"""
        # Update with the data of the current stimulus:
        current_stim_dict = self.current_stimulus.get_state()
        new_dict = dict(current_stim_dict,
                        t_start=self.t - self.current_stimulus.elapsed, t_stop=self.t)
        if self.log_print:
            print(new_dict)
        self.log.append(new_dict)

    def update_dynamic_log(self):
        if isinstance(self.current_stimulus, DynamicStimulus):
            self.dynamic_log.update_list((self.t,) + self.current_stimulus.get_dynamic_state())

    def reset(self):
        self.t_start = None
        self.t_end = None
        self.completed = False
        self.t = 0
        for stimulus in self.stimuli:
            stimulus._started = None
            stimulus.elapsed = 0.0

        self.i_current_stimulus = 0
        self.current_stimulus = self.stimuli[0]

    def get_duration(self):
        total_duration = 0
        for stim in self.stimuli:
            total_duration += stim.duration
        return total_duration

    def print(self):
        string = ''
        for stim in self.stimuli:
            string += '-' + stim.name

        print(string)


class DynamicLog(Accumulator):
    def __init__(self, stimuli):
        super().__init__()
        # it is assumed the first dynamic stimulus has all the fields
        self.starting_time = 0
        for stimulus in stimuli:
            if isinstance(stimulus, DynamicStimulus):
                self.header_list = ['t'] + stimulus.dynamic_parameters
        self.stored_data = []

    def update_list(self, data):
        self.stored_data.append(data)

    def reset(self):
        self.stored_data = []

