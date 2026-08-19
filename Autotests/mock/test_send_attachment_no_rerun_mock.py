"""
Regression test: one send-attachment call must not stall the agent loop.

Commands are evaluated under collapse/superpose, so a side-effecting call
without a cut is re-executed on every backtrack. With the cut missing the
agent never returned from send-attachment and never reached the next
iteration until the process was restarted.

The mock comm channel does not implement send_attachment, so the call ends in
the SEND-ATTACHMENT-UNSUPPORTED-CHANNEL branch. That branch still invokes
commChannelSendAttachment, which is what gets re-executed.

Run:
    pytest test_send_attachment_no_rerun_mock.py -s
"""
import time

from helpers import (
    Checker, make_prompt, wait_for_file, wait_for_history_block,
)

PROBE_DIR = "/tmp/send_attachment_probe"
MARKER = f"{PROBE_DIR}/done.txt"
ATTACHMENT_ID = "376fb042-0de7-4e7b-97ad-e261d1d434f7"
WAIT = 60


def test_send_attachment_does_not_stall_loop_mock(llm, comm):
    with Checker("send-attachment does not stall the loop (mock)",
                 cleanup_dirs=[PROBE_DIR]) as c:
        print(f"\n=== OmegaClaw: send-attachment rerun mock (run-id {c.run_id}) ===",
              flush=True)

        c.verify_clean()

        start_ts = int(time.time()) - 1

        c.step("send prompt with a mocked send-attachment response")
        prompt = make_prompt(c.run_id, "Send the prepared attachment to the user.")
        llm.set_answer(
            prompt,
            f'(send-attachment "{ATTACHMENT_ID}" "here is the file") '
            f'(shell "mkdir -p {PROBE_DIR}") '
            f'(write-file "{MARKER}" "reached")',
        )
        if not comm.send_message(prompt):
            c.fail("comm", "could not deliver prompt within 60s")
        c.ok("comm", f"run-id={c.run_id}")

        c.step("wait for the command that follows send-attachment")
        mtime = wait_for_file(MARKER, start_ts, timeout=WAIT)
        if mtime is None:
            c.fail(
                "loop advanced",
                f"{MARKER} not written within {WAIT}s: the loop never returned "
                "from send-attachment",
            )
        c.ok("loop advanced", f"after {mtime - start_ts}s")

        c.step("verify the iteration completed")
        block = wait_for_history_block(c.run_id, timeout=WAIT)
        if block is None:
            c.fail("iteration completed", "no history block for this run")
        c.ok("iteration completed", f"{len(block)} bytes of history")

        c.done()
