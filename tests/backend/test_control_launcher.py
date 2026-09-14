from types import SimpleNamespace
from unittest.mock import patch

import phase2
import pytest


@pytest.mark.parametrize("missing", [False, True])
def test_launcher_preloads_all_pinned_project_images(missing):
    def run(args, **kwargs):
        return SimpleNamespace(returncode=int(missing) if args[1:3] == ["image", "inspect"] else 0)

    with patch.object(phase2.subprocess, "run", side_effect=run) as command:
        phase2.ensure_project_images()
    calls = [call.args[0] for call in command.call_args_list]
    images = [phase2.IMAGES[kind] for kind in ("auth", "rest", "storage", "realtime", "s3")]
    assert [args[-1] for args in calls if args[1:3] == ["image", "inspect"]] == images
    assert [args[-1] for args in calls if args[1] == "pull"] == (images if missing else [])
