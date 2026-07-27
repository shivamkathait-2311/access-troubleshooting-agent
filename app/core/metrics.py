from prometheus_client import Counter, Gauge, Histogram

diagnostic_runs_total = Counter(
    "diagnostic_runs_total",
    "Total number of diagnostic runs started",
    ["outcome"],
)

verdicts_total = Counter(
    "verdicts_total",
    "Total verdicts produced per funnel step",
    ["step", "result"],
)

remediation_actions_total = Counter(
    "remediation_actions_total",
    "Total remediation actions executed",
    ["tier", "outcome"],
)

connector_call_duration_seconds = Histogram(
    "connector_call_duration_seconds",
    "Latency of connector SPI calls",
    ["connector", "operation"],
)

killswitch_engaged = Gauge(
    "killswitch_engaged",
    "1 if a kill switch is currently engaged, else 0",
    ["scope"],
)
