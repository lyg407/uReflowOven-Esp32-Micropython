import machine
import utime


class OvenControl:
    states = ("wait", "ready", "start", "preheat", "soak", "reflow", "cool")

    def __init__(self, oven_obj, temp_sensor_obj, reflow_profiles_obj, gui_obj, buzzer_obj, timer_obj, config):
        self.config = config
        self.oven = oven_obj
        self.gui = gui_obj
        self.beep = buzzer_obj
        self.tim = timer_obj
        self.profiles = reflow_profiles_obj
        self.sensor = temp_sensor_obj
        self.ontemp = self.sensor.get_temp()
        self.offtemp = self.ontemp
        self.ontime = 0
        self.offtime = 0
        self.control = False
        self.reflow_start = 0
        self.oven_state = 'ready'
        self.last_state = 'ready'
        self.timediff = 0
        self.stage_text = ''
        self.temp_points = []
        self.has_started = False
        self.start_time = None
        self.oven_reset()
        self.format_time(0)
        self.gui.add_reflow_process_start_cb(self.reflow_process_start)
        self.gui.add_reflow_process_stop_cb(self.reflow_process_stop)

    def set_oven_state(self, state):
        self.oven_state = state
        self._oven_state_change_timing_alert()

    def get_profile_temp(self, seconds):
        x1 = self.profiles.get_temp_profile()[0][0]
        y1 = self.profiles.get_temp_profile()[0][1]
        for point in self.profiles.get_temp_profile():
            x2 = point[0]
            y2 = point[1]
            if x1 <= seconds < x2:
                temp = y1 + (y2 - y1) * (seconds - x1) // (x2 - x1)
                return temp
            x1 = x2
            y1 = y2
        return 0

    def oven_reset(self):
        self.ontime = 0
        self.offtime = 0
        self.reflow_start = 0
        self.oven_enable(False)

    def oven_enable(self, enable):
        self.control = enable
        if enable:
            self.oven.on()
            self.gui.led_turn_on()
            self.offtime = 0
            self.ontime = utime.time()
            self.ontemp = self.sensor.get_temp()
            print("oven on")
        else:
            self.oven.off()
            self.gui.led_turn_off()
            self.offtime = utime.time()
            self.ontime = 0
            self.offtemp = self.sensor.get_temp()
            print("oven off")

    def format_time(self, sec):
        minutes = sec // 60
        seconds = int(sec) % 60
        time = "{:02d}:{:02d}".format(minutes, seconds, width=2)
        self.gui.set_timer_text(time)

    def _reflow_temp_control(self):
        stages = self.profiles.get_profile_stages()
        temp = self.sensor.get_temp()
        if self.oven_state == "ready":
            self.oven_enable(False)
        if self.oven_state == "wait":
            self.oven_enable(False)
            if temp < 50:
                self.set_oven_state("start")
        if self.oven_state == "start":
            # self.set_oven_state('start')
            self.oven_enable(True)
        if self.oven_state == "start" and temp >= 50:
            self.set_oven_state("preheat")
        # if self.oven_state == "preheat":
        #     self.set_oven_state('preheat')
        if self.oven_state == "preheat" and temp >= stages.get("soak")[1]:
            self.set_oven_state("soak")
        # if self.oven_state == "soak":
        #     self.set_oven_state('soak')
        if self.oven_state == "soak" and temp >= stages.get("reflow")[1]:
            self.set_oven_state("reflow")
        # if self.oven_state == "reflow":
        #     self.set_oven_state('reflow')
        if (self.oven_state == "reflow"
                and temp >= stages.get("cool")[1]
                and self.reflow_start > 0
                and (utime.time() - self.reflow_start >=
                     stages.get("cool")[0] - stages.get("reflow")[0])):
            self.set_oven_state("cool")
        if self.oven_state == "cool":
            self.oven_enable(False)
        # if self.oven_state == 'cool' and self.timediff >= self.profiles.get_time_range()[-1]:
        if self.oven_state == 'cool' and len(self.temp_points) >= len(self.gui.null_chart_point_list):
            self.beep.activate('Stop')
            self.has_started = False

        if self.oven_state in ("start", "preheat", "soak", "reflow"):
            # oven temp control here
            # check range of calibration to catch any humps in the graph
            checktime = 0
            checktimemax = self.config.get("calibrate_seconds")
            checkoven = False
            if not self.control:
                checktimemax = max(0, self.config.get("calibrate_seconds") -
                                   (utime.time() - self.offtime))
            while checktime <= checktimemax:
                check_temp = self.get_profile_temp(int(self.timediff + checktime))
                if (temp + self.config.get("calibrate_temp")*checktime/checktimemax
                        < check_temp):
                    checkoven = True
                    break
                checktime += 5
            if not checkoven:
                # hold oven temperature
                if (self.oven_state in ("start", "preheat", "soak") and
                        self.offtemp > self.sensor.get_temp()):
                    checkoven = True
            self.oven_enable(checkoven)

    def _chart_update(self):
        low_end = self.profiles.get_temp_range()[0]
        oven_temp = self.sensor.get_temp()
        if oven_temp >= low_end:
            self.temp_points.append(int(oven_temp))
            self.gui.chart_update(self.temp_points)

    def _elapsed_timer_update(self):
        now = utime.time()
        self.timediff = int(now - self.start_time)
        self.format_time(self.timediff)

    def _start_timimg(self):
        # the elapsed timer starts here
        if self.oven_state == 'start' and (self.last_state == 'ready' or self.last_state == 'wait'):
            self.start_time = utime.time()
        # the reflow timer starts here
        if self.oven_state == 'reflow' and self.last_state != "reflow":
            self.reflow_start = utime.time()

    def _oven_state_change_timing_alert(self):
        self._start_timimg()
        if self.oven_state != self.last_state:
            if self.oven_state == 'start':
                # self.beep.play_song('Start')
                self.beep.activate('Start')
            elif self.oven_state == 'cool':
                self.beep.activate('SMBwater')
            elif self.oven_state == 'ready':
                pass
            elif self.oven_state == 'wait':
                # self.beep.play_song('Next')
                self.beep.activate('TAG')
            else:
                self.beep.activate('Next')
            # Update stage message to user
            self._stage_message_update()
            self.last_state = self.oven_state

    def _stage_message_update(self):
        if self.oven_state == "ready":
            self.stage_text = "#003399 Ready#"
        if self.oven_state == "start":
            self.stage_text = "#009900 Starting#"
        if self.oven_state == "preheat":
            self.stage_text = "#FF6600 Preheat#"
        if self.oven_state == "soak":
            self.stage_text = "#FF0066 Soak#"
        if self.oven_state == "reflow":
            self.stage_text = "#FF0000 Reflow#"
        if self.oven_state == "cool" or self.oven_state == "wait":
            self.stage_text = "#0000FF Cool Down, Open Door#"
        self.gui.set_stage_text(self.stage_text)

    def _control_cb_handler(self):
        if self.has_started:
            # Oven temperature control logic
            self._reflow_temp_control()
            # # Update stage message to user
            # self._stage_message_update()
            if self.oven_state in ("start", "preheat", "soak", "reflow", 'cool'):
                # Update gui temp chart
                self._chart_update()
                # Update elapsed timer
                self._elapsed_timer_update()
        else:
            self.tim.deinit()
            # Same effect as click Stop button on GUI
            self.gui.set_reflow_process_on(False)

    def reflow_process_start(self):
        """
        This method is called by clicking Start button on the GUI
        """
        # clear the chart temp list
        self.temp_points = []
        # reset the timer for the whole process
        # self.start_time = utime.time()
        # mark the progress to start
        self.has_started = True
        # set the oven state to start
        if self.sensor.get_temp() >= 50:
            self.set_oven_state('wait')
        else:
            self.set_oven_state('start')
        # initialize the hardware timer to call the control callback once every 1s
        self.tim.init(period=1000, mode=machine.Timer.PERIODIC, callback=lambda t: self._control_cb_handler())

    def reflow_process_stop(self):
        """
        This method is called by clicking Stop button on the GUI
        """
        self.tim.deinit()
        self.has_started = False
        self.oven_reset()
        self.start_time = None
        self.timediff = 0
        self.format_time(self.timediff)
        self.stage_text = ''
        self.gui.set_stage_text(self.stage_text)
        self.set_oven_state('ready')
