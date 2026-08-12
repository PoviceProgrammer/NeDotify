"""
NeDotify - Plugin System
Loads external user plugins dynamically from the `plugins` folder.
"""

import os
import sys
import importlib
import logging

logger = logging.getLogger(__name__)

class PluginManager:
    def __init__(self, app_core):
        self._core = app_core
        self.plugins = []


        self.plugins_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'plugins'
        )
        os.makedirs(self.plugins_dir, exist_ok=True)


        if self.plugins_dir not in sys.path:
            sys.path.insert(0, self.plugins_dir)

    def load_plugins(self):
        """Discover and load all valid plugins."""
        for entry in os.listdir(self.plugins_dir):
            plugin_path = os.path.join(self.plugins_dir, entry)

            is_file_plugin = os.path.isfile(plugin_path) and entry.endswith('.py') and entry != '__init__.py'
            is_dir_plugin = os.path.isdir(plugin_path) and os.path.isfile(os.path.join(plugin_path, '__init__.py'))

            if is_file_plugin or is_dir_plugin:
                module_name = entry[:-3] if is_file_plugin else entry
                self._load_plugin(module_name)

    def _load_plugin(self, module_name):

        try:
            if module_name in sys.modules:
                module = importlib.reload(sys.modules[module_name])
            else:
                module = importlib.import_module(module_name)

            if hasattr(module, 'setup') and callable(module.setup):
                module.setup(self._core)
                self.plugins.append(module)
                logger.info(f'Loaded plugin: {module_name}')
            else:
                logger.warning(f'Plugin {module_name} missing setup(app_core) function. Ignored.')
        except Exception as e:
            logger.error(f'Failed to load plugin {module_name}: {e}')



    def unload_all(self):
        """Call teardown on all plugins if they support it."""
        for module in self.plugins:
            try:
                if hasattr(module, 'teardown') and callable(module.teardown):
                    module.teardown()
            except Exception as e:
                logger.error(f'Error unloading plugin {module.__name__}: {e}')

        self.plugins.clear()