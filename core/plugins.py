"""
NeDotify - Plugin System
Loads external user plugins from the `plugins` folder by explicit file location.

The plugins folder is never added to sys.path: doing so let a user-writable
directory shadow stdlib modules (plugins/json.py) for the whole process. Modules
are loaded through importlib and registered under the `aura_plugins.` namespace.
Loading is opt-in via the `general.plugins_enabled` setting (default OFF).
"""

import os
import sys
import importlib.util
import logging

logger = logging.getLogger(__name__)

PLUGIN_NAMESPACE = 'aura_plugins'


class PluginManager:
    def __init__(self, app_core):
        self._core = app_core
        self.plugins = []

        self.plugins_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'plugins'
        )
        try:
            os.makedirs(self.plugins_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f'Could not create plugins dir {self.plugins_dir}: {e}')

    def _plugins_enabled(self) -> bool:
        """Plugins execute arbitrary user code, so they stay off unless enabled."""
        settings = getattr(self._core, 'settings', None)
        if settings is None:
            return False
        try:
            return bool(settings.get('general', 'plugins_enabled', False))
        except Exception as e:
            logger.warning(f'Could not read general.plugins_enabled, keeping plugins disabled: {e}')
            return False

    def load_plugins(self):
        """Discover and load all valid plugins."""
        if not self._plugins_enabled():
            logger.info('Plugins are disabled (general.plugins_enabled = false); skipping plugin discovery.')
            return

        try:
            entries = sorted(os.listdir(self.plugins_dir))
        except Exception as e:
            logger.warning(f'Could not list plugins dir {self.plugins_dir}: {e}')
            return

        for entry in entries:
            plugin_path = os.path.join(self.plugins_dir, entry)

            is_file_plugin = os.path.isfile(plugin_path) and entry.endswith('.py') and entry != '__init__.py'
            is_dir_plugin = os.path.isdir(plugin_path) and os.path.isfile(os.path.join(plugin_path, '__init__.py'))

            if is_file_plugin:
                self._load_plugin(entry[:-3], plugin_path)
            elif is_dir_plugin:
                self._load_plugin(entry, os.path.join(plugin_path, '__init__.py'))

    def _load_plugin(self, module_name, file_path=None):
        if file_path is None:
            candidate = os.path.join(self.plugins_dir, f'{module_name}.py')
            package_init = os.path.join(self.plugins_dir, module_name, '__init__.py')
            file_path = candidate if os.path.isfile(candidate) else package_init

        qualified_name = f'{PLUGIN_NAMESPACE}.{module_name}'

        try:
            if not os.path.isfile(file_path):
                logger.warning(f'Plugin {module_name} has no loadable entry file. Ignored.')
                return

            spec = importlib.util.spec_from_file_location(
                qualified_name,
                file_path,
                submodule_search_locations=[os.path.dirname(file_path)],
            )
            if spec is None or spec.loader is None:
                logger.warning(f'Plugin {module_name} could not be prepared for import. Ignored.')
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[qualified_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(qualified_name, None)
                raise

            if hasattr(module, 'setup') and callable(module.setup):
                module.setup(self._core)
                self.plugins.append(module)
                logger.info(f'Loaded plugin: {module_name}')
            else:
                sys.modules.pop(qualified_name, None)
                logger.warning(f'Plugin {module_name} missing setup(app_core) function. Ignored.')
        except Exception as e:
            logger.error(f'Failed to load plugin {module_name}: {e}', exc_info=True)

    def unload_all(self):
        """Call teardown on all plugins if they support it."""
        for module in self.plugins:
            try:
                if hasattr(module, 'teardown') and callable(module.teardown):
                    module.teardown()
            except Exception as e:
                logger.error(f'Error unloading plugin {module.__name__}: {e}', exc_info=True)
            finally:
                sys.modules.pop(getattr(module, '__name__', ''), None)

        self.plugins.clear()
