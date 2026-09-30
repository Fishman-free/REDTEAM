"""RSI Arena: three independent heavy agents (attacker, defender, judge) in Docker,
orchestrated against the PayGate payment SUT with a hash-chained audit trail."""

__all__ = ["config", "audit", "exchange", "constitution", "scoring",
           "runtime", "docker_host", "orchestrator", "reports"]
