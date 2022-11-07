# coding=utf-8
from __future__ import absolute_import
import time
from datetime import datetime, timedelta
import octoprint.plugin
import octoprint.events
from octoprint.util import RepeatedTimer

from dps5005 import Dps5005, Serial_modbus, Import_limits
import piconzero as pz

class ElectroplaterPlugin(octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.ShutdownPlugin
):

    def __init__(self):
        #TODO: create a udev rule to make sure ttyUSB* is always a specific name, or some other solution here
        ser = Serial_modbus('/dev/dps5005', 1, 9600, 8) #TODO: Catch error if we can't connect 
        limits = Import_limits()
        self.psu = Dps5005(ser, limits)
        self.plate_timer = RepeatedTimer(60.0, self.fromTimer, condition=self.condition, on_condition_false=self.plating_done)
        self.pump = pz
        self.pump.init()
        self.start_time = None

    def on_after_startup(self):
        self._logger.info("ProjectQuine Electroplater %s Alive Now!", self._plugin_version)
        self._logger.info("DPS5005 runnin version: %s", self.psu.version())
    
    def on_shutdown(self):
        self.pump.stop()
        # Cleanup Pump objects
        self.pump.cleanup()

    ##~~ Timer handlers
    def fromTimer (self):
        self._logger.info("Periodic Timer fired")
        self._logger.info("Plating at {} volts and currently drawing {} Amps".format(self.psu.voltage(), self.psu.current())) # TODO: Notifiy if there is no current draw
        self._logger.info("Total Plating time is: {}".format(datetime.now() - self.start_time))
        self._logger.info("##################################################")

    def condition(self):
        time_limit = timedelta(hours=int(self._settings.get(["plating_time"])))
        return ((datetime.now() - self.start_time) < time_limit)

    def plating_done(self):
        self._logger.info("Maximum Plating time exceeded, shutting down")
        #Stop PSU
        self.psu.onoff(RWaction='w', value=0)
        # Set the Bed temperature to 0
        self._printer.set_temperature("bed", 0.0)
        # Move Extruder head with anode out of solution
        self._printer.commands(["T1","G1 Z50", "G1 X362"])

        # Cleanup Pump objects
        self.pump.cleanup()
        self._logger.info("Electroplating ended at {}".format(datetime.now()))

    ##~~ SettingsPlugin mixin

    def get_settings_defaults(self):
        return dict(
            plate_after_print = False,
            plating_time = 6, # Number of hours to plate for
            plating_voltage = 1.00,
            max_current = 0.1, # Maximum allowed current in Amps
            bed_temperature = 60,
            solution_volume = 100,
            cup_height = 25, # Height of full print in mm
        )

    def get_template_configs(self):
        return [dict(type = "settings", custom_bindings=False)]

    ##~~ EventPlugin API

    def on_event(self, event, payload):

        if event == "PrintDone":
            self._logger.info("Does this print need to be electroplated? {}".format( "Yes" if self._settings.get(["plate_after_print"]) else "No"))
            if self._settings.get(["plate_after_print"]):
                # TODO: Check that our PSU, Pump are both connected and functional, if not: notify and error out
                self._logger.info("Print ended, starting Plating process.")
                volts = self._settings.get(["plating_voltage"])
                amps = self._settings.get(["max_current"])
                hours = self._settings.get(["plating_time"])
                self._logger.info("Starting electroplating with {} volts @ max {} Amps for {} hours".format(volts,amps,hours))

                # Set the Bed temperature
                self._printer.set_temperature("bed", float(self._settings.get(["bed_temperature"])))
                
                # Set PSU Voltage & Current
                self._logger.info("PSU model is {}".format(self.psu.model()))
                self.psu.voltage_set(RWaction='w', value=float(self._settings.get(["plating_voltage"])))
                time.sleep(3)
                self.psu.current_set(RWaction='w', value=float(self._settings.get(["max_current"])))
                
                # Position Anode and pump pipe above model
                # switch to T1 extruder and move it to x125 and y195
                self._printer.commands("G90") # set absolute positioning mode
                # self._printer.commands("T0") # select first extruder
                # Deploy the annode
                self._printer.commands("T1") # Select second extruder with anode and pump
                self._printer.commands("G1 X340") # Move extruder beneath bump ledge
                self._printer.commands("G1 Z329") # Move up to bump into latch position
                self._printer.commands("G1 Z300") # Move up to bump into latch position
                self._printer.commands("G1 X197 Y172") # Position anode at center of build plate
                self._logger.info("Pausing to allow extruder to position")
                self._printer.commands("G1 Z{}".format(int(self._settings.get(["cup_height"]))-5))
                time.sleep(180) # Pause to allow the extruder to position itself
                
                self._logger.info("Powering Up PSU")
                self.psu.onoff(RWaction='w', value=1) # Apply power to the electroplating circuit
                # Fill the model's cup with electrolyte solution
                self._logger.info("Starting Solution pump")
                
                while True:
                    # Run a loop until we detect current flow in our anode
                    current = self.psu.current()
                    self._logger.info("Plating at {} volts and currently drawing {} Amps".format(self.psu.voltage(), current))
                    if float(current) == 0.0: # TODO: We need some fail safe here or a timeout
                        self.pump.setMotor(1,-127) # TODO: convert the ml volume in settings to time based on ~1.255ml/sec
                        time.sleep(2)
                    else:
                        self._logger.info("Current is flowing...")
                        self.pump.stop() # Stop the pump
                        self.pump.cleanup() # Cleanup Pump objects
                        self._logger.info("Stopped pump")
                        break

                # Move the anode down 10mm into cup
                self._printer.commands("G1 Z{}".format(int(self._settings.get(["cup_height"]))-10))
                # Start Timer
                self._logger.info("Starting Plating timer...")
                self.start_time = datetime.now()
                self.plate_timer.start()

            else:
                print("We don't need to plate this one!")
        
    ##~~ AssetPlugin mixin

    def get_assets(self):
        # Define your plugin's asset files to automatically include in the
        # core UI here.
        return {
            "js": ["js/electroplater.js"],
            "css": ["css/electroplater.css"],
            "less": ["less/electroplater.less"]
        }

    ##~~ Softwareupdate hook

    def get_update_information(self):
        # Define the configuration for your plugin to use with the Software Update
        # Plugin here. See https://docs.octoprint.org/en/master/bundledplugins/softwareupdate.html
        # for details.
        return {
            "electroplater": {
                "displayName": "Electroplater Plugin",
                "displayVersion": self._plugin_version,

                # version check: github repository
                "type": "github_release",
                "user": "shaunmulligan",
                "repo": "ElectroPlater",
                "current": self._plugin_version,

                # update method: pip
                "pip": "https://github.com/shaunmulligan/ElectroPlater/archive/{target_version}.zip",
            }
        }


# If you want your plugin to be registered within OctoPrint under a different name than what you defined in setup.py
# ("OctoPrint-PluginSkeleton"), you may define that here. Same goes for the other metadata derived from setup.py that
# can be overwritten via __plugin_xyz__ control properties. See the documentation for that.
__plugin_name__ = "Electroplater Plugin"


# Set the Python version your plugin is compatible with below. Recommended is Python 3 only for all new plugins.
# OctoPrint 1.4.0 - 1.7.x run under both Python 3 and the end-of-life Python 2.
# OctoPrint 1.8.0 onwards only supports Python 3.
__plugin_pythoncompat__ = ">=3,<4"  # Only Python 3

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = ElectroplaterPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
