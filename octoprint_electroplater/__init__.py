# coding=utf-8
from __future__ import absolute_import
import time
import octoprint.plugin
import octoprint.events

from dps5005 import Dps5005, Serial_modbus, Import_limits

class ElectroplaterPlugin(octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin
):

    def __init__(self):
        ser = Serial_modbus('/dev/ttyUSB1', 1, 9600, 8) #TODO: Catch error if we can't connect
        limits = Import_limits()
        self.psu = Dps5005(ser, limits)

    def on_after_startup(self):
        self._logger.info("ProjectQuine Electroplater %s Alive Now!", self._plugin_version)
        self._logger.info("DPS5005 runnin version: %s", self.psu.version())
        
    ##~~ SettingsPlugin mixin

    def get_settings_defaults(self):
        return dict(
            plate_after_print = False,
            plating_time = 6,
            plating_voltage = 1.00,
            max_current = 0.1,
            bed_temperature = 60,
        )

    def get_template_configs(self):
        return [dict(type = "settings", custom_bindings=False)]

    ##~~ EventPlugin API

    def on_event(self, event, payload):
        
        if event == "PrintDone": #and self._settings.get(["plate_after_print"]):
            self._logger.info("Print ended, starting Plating process.")
            self._printer.set_temperature("bed", self._settings.get(["bed_temperature"]))
            # Set PSU Voltage & Current
            self.psu.voltage_set(RWaction='w', value=float(self._settings.get(["plating_voltage"])))
            self.psu.current_set(RWaction='w', value=float(self._settings.get(["max_current"])))
            # Start PSU
            self.psu.onoff(RWaction='w', value=1)

            time.sleep(3)
            # Read back current draw
            current = self.psu.current()
            self._logger.info("Plating currently drawing %f Amps", current) # TODO: Notifiy if there is no current draw
        
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
