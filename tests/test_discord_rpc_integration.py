import unittest
from unittest.mock import MagicMock, patch
from core.services.discord_rpc import DiscordRPCService
from core.api import AppApi


class TestDiscordRPCIntegration(unittest.TestCase):
    def setUp(self):
        self.mock_settings = MagicMock()
        self.mock_settings.get.side_effect = lambda cat, key, default=None: True
        self.rpc_service = DiscordRPCService(settings=self.mock_settings)

    def test_discord_rpc_service_initialization(self):
        self.assertIsNotNone(self.rpc_service)
        self.assertEqual(self.rpc_service.client_id, "1329524021200158781")
        self.assertTrue(self.rpc_service.is_enabled())

    def test_discord_rpc_service_disabled_settings(self):
        self.mock_settings.get.side_effect = lambda cat, key, default=None: False
        self.assertFalse(self.rpc_service.is_enabled())

    @patch("core.services.discord_rpc.Presence")
    def test_update_presence_when_connected(self, mock_presence_cls):
        mock_presence = MagicMock()
        mock_presence_cls.return_value = mock_presence

        self.rpc_service.rpc = mock_presence
        self.rpc_service.connected = True

        self.rpc_service.update_presence("Cyberpunk Night", "V_Synth", is_playing=True, duration_sec=180, current_pos_sec=30)
        mock_presence.update.assert_called_once()
        kwargs = mock_presence.update.call_args[1]

        self.assertIn("Cyberpunk Night", kwargs["details"])
        self.assertIn("V_Synth", kwargs["state"])
        self.assertEqual(kwargs["large_image"], "aura_logo")
        self.assertEqual(kwargs["small_image"], "play")
        self.assertIn("start", kwargs)
        self.assertIn("end", kwargs)

    @patch("core.services.discord_rpc.Presence")
    def test_update_presence_paused(self, mock_presence_cls):
        mock_presence = MagicMock()
        mock_presence_cls.return_value = mock_presence

        self.rpc_service.rpc = mock_presence
        self.rpc_service.connected = True

        self.rpc_service.update_presence("Lofi Rain", "ChillCat", is_playing=False)
        mock_presence.update.assert_called_once()
        kwargs = mock_presence.update.call_args[1]

        self.assertIn("Lofi Rain", kwargs["details"])
        self.assertIn("ChillCat", kwargs["state"])
        self.assertEqual(kwargs["small_image"], "pause")

    def test_app_api_discord_rpc_contract(self):
        mock_core = MagicMock()
        mock_core.settings.get.return_value = True
        mock_core.discord_rpc = self.rpc_service

        api = AppApi(mock_core)

        # Test status contract
        status = api.get_discord_rpc_status()
        self.assertIn("enabled", status)
        self.assertIn("connected", status)
        self.assertTrue(status["enabled"])

        # Test toggle contract
        res = api.toggle_discord_rpc(False)
        self.assertTrue(res["success"])
        self.assertFalse(res["enabled"])


if __name__ == "__main__":
    unittest.main()
