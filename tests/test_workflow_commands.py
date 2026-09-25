import sys
from pathlib import Path

import pytest


SRC_PATH = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC_PATH))

import helper


@pytest.mark.parametrize(
    "reply, expected",
    [
        (
            "send Checking the Extensions Hub.\n"
            "workflow-load-instructions extensions-hub",
            '((send "Checking the Extensions Hub.") '
            '(workflow-load-instructions "extensions-hub"))',
        ),
        (
            '(send "Checking the Extensions Hub.")\n'
            '(workflow-load-instructions "extensions-hub")',
            '((send "Checking the Extensions Hub.") '
            '(workflow-load-instructions "extensions-hub"))',
        ),
        (
            "send Here is the upscaled image.\nworkflow-unload-instructions",
            '((send "Here is the upscaled image.") (workflow-unload-instructions))',
        ),
    ],
)
def test_workflow_command_after_send_is_parsed_as_its_own_command(reply, expected):
    assert helper.balance_parentheses(reply) == expected
