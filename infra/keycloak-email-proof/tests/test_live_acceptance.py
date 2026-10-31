import argparse
import importlib.util
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "email_proof_live_acceptance",
    Path(__file__).resolve().parents[1] / "live_acceptance.py",
)
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class AcceptanceFencesTest(unittest.TestCase):
    def setUp(self):
        live.ROOT = None
        live.OWNER = "own-test-nonce"
        live.HTTP_PORT = 29480
        live.MAIL_PORT = 29425
        live.ORIGIN = "http://127.0.0.1:29480"
        live.CALLBACK = "http://127.0.0.1:29481/callback"

    def args(self, state, jar):
        return argparse.Namespace(
            run_isolated_http_h2=True,
            state=state,
            jar=jar,
            http_port=29480,
            mail_port=29425,
        )

    def test_explicit_opt_in_is_required_before_filesystem_or_docker(self):
        args = self.args(Path("unused"), Path("unused.jar"))
        args.run_isolated_http_h2 = False
        with patch.object(live, "docker") as docker:
            with self.assertRaisesRegex(ValueError, "explicit"):
                live.configure(args)
            docker.assert_not_called()

    def test_checkout_or_existing_state_is_refused_before_docker(self):
        for state in (live.REPO / "not-a-private-state", Path(tempfile.gettempdir())):
            with self.subTest(state=state), patch.object(live, "docker") as docker:
                with self.assertRaisesRegex(ValueError, "new and outside"):
                    live.configure(self.args(state, Path("unused.jar")))
                docker.assert_not_called()

    def test_remote_engine_is_rejected_before_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jar = root / "provider.jar"
            jar.write_bytes(b"test-only")
            target = root / "new-private-state"
            context = [{"Endpoints": {"docker": {"Host": "tcp://remote.example:2376"}}}]
            with patch.object(live, "docker", return_value=json.dumps(context)):
                with patch.dict("os.environ", {}, clear=True):
                    with self.assertRaisesRegex(ValueError, "local Docker"):
                        live.configure(self.args(target, jar))
            self.assertFalse(target.exists())

    def test_only_exact_owned_loopback_endpoints_are_permitted(self):
        live.check_url("http://127.0.0.1:29480/realms/test")
        live.check_url("http://127.0.0.1:29425/api/v1/messages")
        for address in (
            "http://example.com:29480/",
            "http://localhost:29480/",
            "http://127.0.0.1:18443/",
            "http://user@127.0.0.1:29480/",
            "https://127.0.0.1:29480/",
        ):
            with self.subTest(address=address), self.assertRaises(ValueError):
                live.check_url(address)

    def test_callback_prefix_does_not_accept_another_path_or_host(self):
        self.assertTrue(live.is_callback(live.CALLBACK + "?code=example"))
        for address in (
            live.CALLBACK + ".other?code=example",
            "http://other:29481/callback",
        ):
            self.assertFalse(live.is_callback(address))

    def test_cleanup_validates_all_ownership_before_stopping_any_container(self):
        live.KC = "own-keycloak"
        live.SMTP = "own-mail"
        with (
            patch.object(
                live,
                "owned_container",
                side_effect=[{"State": {"Running": True}}, ValueError("wrong owner")],
            ),
            patch.object(live, "docker") as docker,
        ):
            with self.assertRaisesRegex(ValueError, "wrong owner"):
                live.stop_owned()
            docker.assert_not_called()

    def test_container_name_or_owner_label_mismatch_refuses_cleanup(self):
        for value in (
            {"Name": "/another", "Config": {"Labels": {live.LABEL: live.OWNER}}},
            {"Name": "/expected", "Config": {"Labels": {live.LABEL: "someone-else"}}},
        ):
            result = SimpleNamespace(returncode=0, stdout=json.dumps([value]))
            with patch.object(live.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(ValueError, "not owned"):
                    live.owned_container("expected")

    def test_local_requests_disable_environment_proxies_and_redirects(self):
        request = urllib.request.Request(live.ORIGIN + "/test")
        with patch.object(live.urllib.request, "build_opener") as build:
            live.local_open(request)
            handlers = build.call_args.args
            self.assertIsInstance(handlers[0], urllib.request.ProxyHandler)
            self.assertEqual({}, handlers[0].proxies)
            self.assertIsInstance(handlers[1], live.NoRedirect)

    def test_user_count_does_not_treat_authentication_error_as_a_one_user_list(self):
        for response in ((401, {"error": "expired"}), (200, {"unexpected": "object"})):
            with patch.object(live, "api", return_value=response):
                with self.assertRaisesRegex(ValueError, "successful list"):
                    live.provider_users(live.ORIGIN + "/admin/realms/test", "test-only")
        with patch.object(live, "api", return_value=(200, [])):
            self.assertEqual([], live.provider_users(live.ORIGIN, "test-only"))


if __name__ == "__main__":
    unittest.main()
