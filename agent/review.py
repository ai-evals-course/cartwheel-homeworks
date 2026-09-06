"""The refund review surface: a CLI a support operator uses to clear the
above threshold refund queue (Homework 8, Part D).

Module 1 left the approval seam open: ``issue_refund_logic`` writes a
``queued_for_approval`` refund and stops, and nothing ever decides it. The
run-loop pause in ``agent/cli.py`` happens earlier: it asks whether the refund
tool may run at all. This tool handles the later decision. A support operator
opens the queue, reads each pending refund's decision record (Artifact D), and
approves or denies the refund. The later decision writes an audit row, and an
approval settles the order.

Design (fixed):
  - Authorization is in code. This tool builds a ``support`` auth context and
    the approval functions enforce support-only; a non-support operator cannot
    approve. Do not weaken that.
  - The reviewer reads the decision record, not the transcript. For each
    pending refund the loop prints ``render_decision_record`` and asks for a
    decision plus a reason, then calls ``approve_refund`` / ``reject_refund``.

Usage:
    uv run python -m agent.review               # review as the default support user
    uv run python -m agent.review --user 9502   # a specific support operator

The DB/arg plumbing and the support-context construction are PROVIDED. The
review LOOP body (iterate the queue, render each record, prompt, decide) is
your seam, marked ``### YOUR CODE HERE (m4)``.
"""

from __future__ import annotations

import argparse

from agent import db
from agent.approvals import (
    approve_refund,
    ensure_approvals_table,
    list_pending_refunds,
    reject_refund,
    render_decision_record,
)
from agent.auth import AuthContext

# The default demo support operator, matching agent/cli.py's DEFAULT_USERS.
DEFAULT_SUPPORT_USER = 9501


def resolve_support(user_id: int | None) -> AuthContext:
    """Build the support auth context from the users table. PROVIDED.

    The operator must have role ``support``; the approval functions enforce
    support-only in code, and this refuses a non-support user id up front so
    the operator gets a clear message instead of a per-refund denial.
    """
    with db.connection() as conn:
        user = db.get_user(conn, user_id if user_id is not None else DEFAULT_SUPPORT_USER)
    if user is None:
        raise SystemExit(f"no such user id: {user_id}")
    if user.role != "support":
        raise SystemExit(
            f"user {user.id} has role '{user.role}', not 'support'; the review tool "
            "is for support operators (authorization is enforced in code)"
        )
    return AuthContext(user_id=user.id, role=user.role, store_id=user.store_id)


def review_queue(operator: AuthContext) -> None:
    """Walk the pending-refund queue and record a decision for each. YOUR SEAM.

    The plumbing hands you an open connection with the ``approvals`` table
    ensured and the support ``operator`` context. Your job is the review loop:

      1. Load the queue with ``list_pending_refunds(conn)``. If it is empty,
         print that there is nothing to review and return.
      2. For each pending refund, print its decision record with
         ``render_decision_record(conn, refund_id)`` so the operator reviews
         the record, not the transcript.
      3. Prompt the operator for a decision (approve / deny / skip) and a
         non-empty reason. Read with ``input(...)``.
      4. Call ``approve_refund(conn, refund_id, operator, reason)`` or
         ``reject_refund(conn, refund_id, operator, reason)`` and print the
         structured result (an approval settles the order; a denial leaves it).
         "skip" moves on without a decision, so the refund stays queued.
      5. Handle a re-run cleanly: an ``already_decided`` result means someone
         decided it since the queue was read; print it and continue.

    Keep it small and readable. This is the human step in the human-in-the-loop
    control; the code below it (``approve_refund`` / ``reject_refund``) is what
    actually authorizes and audits. Do not bypass those functions.
    """
    with db.connection() as conn:
        ensure_approvals_table(conn)
        ### YOUR CODE HERE (m4)
        raise NotImplementedError(
            "m4: implement the review loop (render each pending refund's decision "
            "record, prompt for a decision and reason, and call approve_refund / "
            "reject_refund)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review and clear the Cartwheel above-threshold refund queue."
    )
    parser.add_argument(
        "--user",
        type=int,
        default=None,
        help="support user id (defaults to the demo support operator)",
    )
    args = parser.parse_args()
    operator = resolve_support(args.user)
    print(f"Cartwheel refund review | operator={operator.user_id} (support)")
    review_queue(operator)


if __name__ == "__main__":
    main()
