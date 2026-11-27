"""Find and delete Wi-Lab's firewall rules by their `--comment` (REV-17).

Every Wi-Lab rule carries a comment naming its owner (`wilab-nat-<net>`,
`wilab-portal-<net>`, ...). These helpers list a chain with `-S` and delete
the matching rules or chains, in one place for NAT, captive portal and host
guard. Callers pass their module's `execute_iptables` as *run*, so tests that
replace it there also replace it here. They raise CommandError (and ValueError for an unparsable line): each
caller decides whether a failure is fatal or only logged.
"""

import shlex
from collections.abc import Callable
from itertools import pairwise

Runner = Callable[[list[str]], str]


def listing(chain: str | None = None, *, table: str | None = None, run: Runner) -> list[list[str]]:
    """`iptables -S [chain]` split into tokens, one list per rule."""
    prefix = ["-t", table] if table else []
    output = run([*prefix, "-S", *([chain] if chain else [])])
    return [shlex.split(line) for line in output.splitlines() if line.strip()]


def comments(tokens: list[str]) -> list[str]:
    """The `--comment` values of one rule."""
    return [value for option, value in pairwise(tokens) if option == "--comment"]


def delete_commented(
    chain: str, owned: Callable[[str], bool], *, table: str | None = None, run: Runner,
) -> int:
    """Delete the rules of *chain* with a comment that *owned* accepts; returns how many."""
    prefix = ["-t", table] if table else []
    deleted = 0
    for tokens in listing(chain, table=table, run=run):
        if tokens[:2] == ["-A", chain] and any(owned(c) for c in comments(tokens)):
            run([*prefix, "-D", *tokens[1:]])
            deleted += 1
    return deleted


def delete_chains(owned: Callable[[str], bool], *, table: str | None = None, run: Runner) -> None:
    """Flush and delete every user chain whose name *owned* accepts."""
    prefix = ["-t", table] if table else []
    for tokens in listing(table=table, run=run):
        if tokens[:1] == ["-N"] and len(tokens) > 1 and owned(tokens[1]):
            run([*prefix, "-F", tokens[1]])
            run([*prefix, "-X", tokens[1]])
