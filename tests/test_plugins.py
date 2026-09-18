"""
Unit test suite for core/plugins.py (PluginManager).
Tests plugin discovery, opt-in setting, namespace isolation, setup/teardown hooks,
and handling of invalid, missing, or buggy plugins.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

from core.plugins import PluginManager, PLUGIN_NAMESPACE


class TestPluginManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aura_test_plugins_")
        self.mock_core = MagicMock()
        self.mock_core.settings.get.return_value = False

        self.pm = PluginManager(self.mock_core)
        self.pm.plugins_dir = self.temp_dir

    def tearDown(self):
        self.pm.unload_all()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_plugins_disabled_by_default(self):
        """Plugins must remain inactive if general.plugins_enabled is False."""
        self.mock_core.settings.get.return_value = False
        plugin_file = os.path.join(self.temp_dir, "my_plugin.py")
        with open(plugin_file, "w") as f:
            f.write("def setup(core):\n    core.plugin_was_called()\n")

        self.pm.load_plugins()
        self.assertEqual(len(self.pm.plugins), 0)
        self.mock_core.plugin_was_called.assert_not_called()

    def test_load_single_file_plugin(self):
        """Single-file plugin with setup() is loaded and registered in namespace."""
        self.mock_core.settings.get.return_value = True

        plugin_file = os.path.join(self.temp_dir, "valid_plugin.py")
        with open(plugin_file, "w") as f:
            f.write("is_setup = False\n"
                    "def setup(core):\n"
                    "    global is_setup\n"
                    "    is_setup = True\n"
                    "    core.loaded_marker = 123\n")

        self.pm.load_plugins()
        self.assertEqual(len(self.pm.plugins), 1)
        mod = self.pm.plugins[0]
        self.assertTrue(mod.is_setup)
        self.assertEqual(self.mock_core.loaded_marker, 123)
        self.assertIn(f"{PLUGIN_NAMESPACE}.valid_plugin", sys.modules)

    def test_load_directory_package_plugin(self):
        """Directory package with __init__.py and setup() is loaded correctly."""
        self.mock_core.settings.get.return_value = True

        pkg_dir = os.path.join(self.temp_dir, "pkg_plugin")
        os.makedirs(pkg_dir)
        with open(os.path.join(pkg_dir, "__init__.py"), "w") as f:
            f.write("def setup(core):\n"
                    "    core.pkg_marker = 'pkg_ok'\n")

        self.pm.load_plugins()
        self.assertEqual(len(self.pm.plugins), 1)
        self.assertEqual(self.mock_core.pkg_marker, "pkg_ok")
        self.assertIn(f"{PLUGIN_NAMESPACE}.pkg_plugin", sys.modules)

    def test_plugin_missing_setup_ignored(self):
        """Plugin missing setup() function is ignored and cleaned from sys.modules."""
        self.mock_core.settings.get.return_value = True

        plugin_file = os.path.join(self.temp_dir, "no_setup.py")
        with open(plugin_file, "w") as f:
            f.write("variable = 42\n")

        self.pm.load_plugins()
        self.assertEqual(len(self.pm.plugins), 0)
        self.assertNotIn(f"{PLUGIN_NAMESPACE}.no_setup", sys.modules)

    def test_plugin_syntax_error_resilience(self):
        """Plugin with syntax error or crash during import does not crash the host."""
        self.mock_core.settings.get.return_value = True

        plugin_file = os.path.join(self.temp_dir, "broken.py")
        with open(plugin_file, "w") as f:
            f.write("def setup(core):\n    raise RuntimeError('Explosion!')\nsetup(None)\n")

        self.pm.load_plugins()
        self.assertEqual(len(self.pm.plugins), 0)
        self.assertNotIn(f"{PLUGIN_NAMESPACE}.broken", sys.modules)

    def test_unload_all_calls_teardown_and_cleans_sys_modules(self):
        """unload_all calls teardown() on modules and purges sys.modules."""
        self.mock_core.settings.get.return_value = True

        plugin_file = os.path.join(self.temp_dir, "with_teardown.py")
        with open(plugin_file, "w") as f:
            f.write("torn_down = False\n"
                    "def setup(core):\n    pass\n"
                    "def teardown():\n    global torn_down\n    torn_down = True\n")

        self.pm.load_plugins()
        self.assertEqual(len(self.pm.plugins), 1)
        mod = self.pm.plugins[0]

        self.pm.unload_all()
        self.assertEqual(len(self.pm.plugins), 0)
        self.assertTrue(mod.torn_down)
        self.assertNotIn(f"{PLUGIN_NAMESPACE}.with_teardown", sys.modules)
