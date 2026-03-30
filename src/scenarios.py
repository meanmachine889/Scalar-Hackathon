"""Scenario definitions for 3 difficulty levels of incident response tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from src.models import Alert, LogEntry, MetricPoint


@dataclass
class Scenario:
    task_id: str
    task_name: str
    difficulty: str  # easy, medium, hard
    description: str
    max_steps: int
    initial_alerts: list[Alert]
    # service_name -> list of logs
    service_logs: dict[str, list[LogEntry]]
    # service_name -> list of metrics
    service_metrics: dict[str, list[MetricPoint]]
    # command -> output
    available_commands: dict[str, str]
    # Root causes the agent should identify (keywords matched)
    root_causes: list[str]
    # Valid remediations (keywords matched)
    valid_remediations: list[str]
    # Correct team to escalate to
    correct_escalation_teams: list[str]
    # Services that are relevant to investigate
    relevant_services: list[str]
    # Services that are red herrings
    red_herring_services: list[str] = field(default_factory=list)
    # Multi-category root causes (for harder tasks requiring identification of
    # multiple distinct root cause aspects). If non-empty, resolve must match
    # keywords from at least min_root_cause_categories different categories.
    root_cause_categories: dict[str, list[str]] = field(default_factory=dict)
    min_root_cause_categories: int = 1


def _easy_scenario() -> Scenario:
    """Database Connection Pool Exhaustion — single service outage."""
    return Scenario(
        task_id="easy_db_pool",
        task_name="Database Connection Pool Exhaustion",
        difficulty="easy",
        description=(
            "The api-gateway service is returning HTTP 500 errors. "
            "Users are reporting that the application is down. "
            "Investigate, identify the root cause, and resolve the incident."
        ),
        max_steps=15,
        initial_alerts=[
            Alert(
                alert_id="ALT-1001",
                severity="critical",
                service="api-gateway",
                message="HTTP 500 error rate exceeded 50% threshold — 78% of requests failing",
                timestamp="2024-01-15T14:23:00Z",
            ),
            Alert(
                alert_id="ALT-1002",
                severity="warning",
                service="api-gateway",
                message="Response latency p99 > 30s (normally 200ms)",
                timestamp="2024-01-15T14:23:15Z",
            ),
        ],
        service_logs={
            "api-gateway": [
                LogEntry(timestamp="2024-01-15T14:22:45Z", level="ERROR", service="api-gateway",
                         message="Failed to acquire database connection: pool exhausted (active=50, max=50)"),
                LogEntry(timestamp="2024-01-15T14:22:46Z", level="ERROR", service="api-gateway",
                         message="ConnectionPoolExhausted: waited 30000ms for available connection, giving up"),
                LogEntry(timestamp="2024-01-15T14:22:47Z", level="WARN", service="api-gateway",
                         message="Connection leak detector: connection checked out for >60s by thread-handler-42"),
                LogEntry(timestamp="2024-01-15T14:22:48Z", level="ERROR", service="api-gateway",
                         message="Request /api/v1/users failed: unable to obtain database connection"),
                LogEntry(timestamp="2024-01-15T14:20:00Z", level="INFO", service="api-gateway",
                         message="Deployed version 2.14.3 — changelog: added new user analytics query"),
                LogEntry(timestamp="2024-01-15T14:20:30Z", level="WARN", service="api-gateway",
                         message="Slow query detected: SELECT * FROM user_events JOIN analytics ON ... (12.4s)"),
            ],
            "database": [
                LogEntry(timestamp="2024-01-15T14:22:50Z", level="WARN", service="database",
                         message="Max connections reached (50/50). New connection requests queued."),
                LogEntry(timestamp="2024-01-15T14:22:55Z", level="ERROR", service="database",
                         message="Too many connections — rejecting new connection from 10.0.1.15"),
                LogEntry(timestamp="2024-01-15T14:21:00Z", level="INFO", service="database",
                         message="Long-running query detected: analytics join running for 45s (pid 3847)"),
            ],
            "notification-service": [
                LogEntry(timestamp="2024-01-15T14:23:00Z", level="WARN", service="notification-service",
                         message="Email delivery queue backing up — 340 pending notifications"),
                LogEntry(timestamp="2024-01-15T14:23:05Z", level="INFO", service="notification-service",
                         message="Retrying failed email batch: 23 emails to re-queue (SMTP timeout)"),
            ],
        },
        service_metrics={
            "api-gateway": [
                MetricPoint(name="http_error_rate", value=78.2, unit="percent", timestamp="2024-01-15T14:23:00Z"),
                MetricPoint(name="response_latency_p99", value=31200.0, unit="ms", timestamp="2024-01-15T14:23:00Z"),
                MetricPoint(name="active_db_connections", value=50.0, unit="count", timestamp="2024-01-15T14:23:00Z"),
                MetricPoint(name="cpu_usage", value=23.0, unit="percent", timestamp="2024-01-15T14:23:00Z"),
                MetricPoint(name="memory_usage", value=45.0, unit="percent", timestamp="2024-01-15T14:23:00Z"),
            ],
            "database": [
                MetricPoint(name="active_connections", value=50.0, unit="count", timestamp="2024-01-15T14:23:00Z"),
                MetricPoint(name="query_queue_length", value=127.0, unit="count", timestamp="2024-01-15T14:23:00Z"),
                MetricPoint(name="cpu_usage", value=89.0, unit="percent", timestamp="2024-01-15T14:23:00Z"),
                MetricPoint(name="disk_io_util", value=72.0, unit="percent", timestamp="2024-01-15T14:23:00Z"),
            ],
            "notification-service": [
                MetricPoint(name="email_queue_depth", value=340.0, unit="count", timestamp="2024-01-15T14:23:00Z"),
                MetricPoint(name="delivery_success_rate", value=78.0, unit="percent", timestamp="2024-01-15T14:23:00Z"),
            ],
        },
        available_commands={
            "restart api-gateway": "Service api-gateway restarting... OK. Connection pool reset. Active connections: 0/50.",
            "kill-query 3847": "Killed long-running query (pid 3847). Freed 1 connection.",
            "increase-pool-size api-gateway 100": "Connection pool size increased from 50 to 100. Active: 50/100.",
            "rollback api-gateway 2.14.2": "Rolling back api-gateway to v2.14.2... OK. Deployment complete.",
            "show connections api-gateway": "Active: 50/50 | Idle: 0 | Waiting: 127 | Leaked: 3 (thread-handler-42, thread-handler-58, thread-handler-91)",
        },
        root_causes=[
            "connection pool exhausted",
            "pool exhaustion",
            "slow query",
            "analytics query",
            "connection leak",
            "long-running query",
            "bad deploy",
            "version 2.14.3",
        ],
        valid_remediations=[
            "restart",
            "kill-query",
            "kill query",
            "rollback",
            "increase pool",
            "increase-pool-size",
        ],
        correct_escalation_teams=["database", "backend", "platform"],
        relevant_services=["api-gateway", "database"],
        red_herring_services=["notification-service"],
    )


def _medium_scenario() -> Scenario:
    """Cascading Cache Failure — thundering herd to database."""
    return Scenario(
        task_id="medium_cache_cascade",
        task_name="Cascading Cache Failure",
        difficulty="medium",
        description=(
            "Multiple services are experiencing degraded performance. "
            "The user-service, product-service, and order-service are all showing elevated latency. "
            "Customer complaints are increasing. Investigate the cascade and resolve it."
        ),
        max_steps=20,
        initial_alerts=[
            Alert(
                alert_id="ALT-2001",
                severity="critical",
                service="user-service",
                message="Latency p99 spiked to 15s (SLA: 500ms). Error rate 34%.",
                timestamp="2024-01-15T09:45:00Z",
            ),
            Alert(
                alert_id="ALT-2002",
                severity="critical",
                service="product-service",
                message="Latency p99 spiked to 22s (SLA: 300ms). Error rate 41%.",
                timestamp="2024-01-15T09:45:10Z",
            ),
            Alert(
                alert_id="ALT-2003",
                severity="warning",
                service="order-service",
                message="Timeout errors increasing. 12% of orders failing.",
                timestamp="2024-01-15T09:45:20Z",
            ),
            Alert(
                alert_id="ALT-2004",
                severity="warning",
                service="redis-cluster",
                message="Node redis-03 heartbeat lost. Cluster degraded.",
                timestamp="2024-01-15T09:44:30Z",
            ),
        ],
        service_logs={
            "user-service": [
                LogEntry(timestamp="2024-01-15T09:44:55Z", level="ERROR", service="user-service",
                         message="Cache miss for key user:profile:* — falling back to database"),
                LogEntry(timestamp="2024-01-15T09:45:00Z", level="ERROR", service="user-service",
                         message="Redis connection refused: redis-03.internal:6379 — ECONNREFUSED"),
                LogEntry(timestamp="2024-01-15T09:45:01Z", level="WARN", service="user-service",
                         message="Cache fallback: 4,200 concurrent DB queries (normal: ~50)"),
                LogEntry(timestamp="2024-01-15T09:45:05Z", level="ERROR", service="user-service",
                         message="Database connection timeout after 10s — pool saturated"),
            ],
            "product-service": [
                LogEntry(timestamp="2024-01-15T09:44:58Z", level="ERROR", service="product-service",
                         message="Redis READONLY — cannot write to replica. Failover in progress?"),
                LogEntry(timestamp="2024-01-15T09:45:02Z", level="ERROR", service="product-service",
                         message="Cache invalidation failed — stale data may be served"),
                LogEntry(timestamp="2024-01-15T09:45:03Z", level="WARN", service="product-service",
                         message="Thundering herd detected: 8,100 concurrent requests to /api/products"),
            ],
            "order-service": [
                LogEntry(timestamp="2024-01-15T09:45:10Z", level="ERROR", service="order-service",
                         message="Dependency user-service returned 503. Order creation failed."),
                LogEntry(timestamp="2024-01-15T09:45:15Z", level="WARN", service="order-service",
                         message="Circuit breaker OPEN for user-service (5 consecutive failures)"),
            ],
            "redis-cluster": [
                LogEntry(timestamp="2024-01-15T09:44:25Z", level="ERROR", service="redis-cluster",
                         message="Node redis-03 OOM: used_memory=16.1GB, maxmemory=16GB. Evicting keys."),
                LogEntry(timestamp="2024-01-15T09:44:30Z", level="CRITICAL", service="redis-cluster",
                         message="Node redis-03 unresponsive. CLUSTER FAILOVER initiated."),
                LogEntry(timestamp="2024-01-15T09:44:35Z", level="ERROR", service="redis-cluster",
                         message="Failover FAILED: no eligible replica for redis-03 shard."),
                LogEntry(timestamp="2024-01-15T09:44:40Z", level="WARN", service="redis-cluster",
                         message="Slots 10923-16383 now UNMAPPED. Reads/writes to these slots will fail."),
            ],
            "database": [
                LogEntry(timestamp="2024-01-15T09:45:05Z", level="WARN", service="database",
                         message="Connection surge: 350 active (normal: 40). CPU 94%."),
                LogEntry(timestamp="2024-01-15T09:45:10Z", level="ERROR", service="database",
                         message="Max connections reached. Rejecting new connections."),
            ],
        },
        service_metrics={
            "user-service": [
                MetricPoint(name="latency_p99", value=15200.0, unit="ms", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="error_rate", value=34.0, unit="percent", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="cache_hit_rate", value=2.0, unit="percent", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="db_queries_per_sec", value=4200.0, unit="qps", timestamp="2024-01-15T09:45:00Z"),
            ],
            "product-service": [
                MetricPoint(name="latency_p99", value=22000.0, unit="ms", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="error_rate", value=41.0, unit="percent", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="cache_hit_rate", value=0.0, unit="percent", timestamp="2024-01-15T09:45:00Z"),
            ],
            "redis-cluster": [
                MetricPoint(name="connected_nodes", value=2.0, unit="count", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="expected_nodes", value=3.0, unit="count", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="keyspace_misses", value=45000.0, unit="per_min", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="memory_redis03", value=16.1, unit="GB", timestamp="2024-01-15T09:44:25Z"),
            ],
            "database": [
                MetricPoint(name="active_connections", value=350.0, unit="count", timestamp="2024-01-15T09:45:00Z"),
                MetricPoint(name="cpu_usage", value=94.0, unit="percent", timestamp="2024-01-15T09:45:00Z"),
            ],
        },
        available_commands={
            "redis-failover redis-03": "Manual failover initiated for redis-03... Promoting redis-03-replica... FAILED: no replica available.",
            "redis-restart redis-03": "Restarting redis-03 with maxmemory=24GB... OK. Node rejoining cluster. Slots remapped.",
            "redis-add-node redis-04": "Adding new node redis-04... OK. Rebalancing slots... Slots 10923-16383 mapped to redis-04.",
            "enable-rate-limit user-service": "Rate limiter enabled for user-service: 100 req/s per client. Shedding excess traffic.",
            "enable-rate-limit product-service": "Rate limiter enabled for product-service: 200 req/s per client. Shedding excess traffic.",
            "enable-circuit-breaker all": "Circuit breakers enabled on all services with cache fallback to stale data.",
            "scale database replicas 3": "Scaling read replicas from 1 to 3... Provisioning... ETA 2 minutes.",
            "flush-cache user-service": "Cache flushed for user-service. Will repopulate on next requests.",
            "flush-cache product-service": "Cache flushed for product-service. Will repopulate on next requests.",
        },
        root_causes=[
            "redis",
            "cache failure",
            "cache node",
            "redis-03",
            "oom",
            "out of memory",
            "thundering herd",
            "cache miss",
            "slot unmapped",
            "failover failed",
        ],
        valid_remediations=[
            "redis-restart",
            "redis-add-node",
            "rate-limit",
            "rate limit",
            "enable-rate-limit",
            "circuit-breaker",
            "circuit breaker",
            "scale",
        ],
        correct_escalation_teams=["infrastructure", "platform", "cache", "database"],
        relevant_services=["redis-cluster", "user-service", "product-service", "database"],
        red_herring_services=["order-service"],
    )


def _hard_scenario() -> Scenario:
    """Payment Pipeline Corruption — multiple root causes with red herrings."""
    return Scenario(
        task_id="hard_payment_corruption",
        task_name="Payment Pipeline Corruption",
        difficulty="hard",
        description=(
            "SEVERITY: P1 — Payment processing is partially failing. Some charges are being "
            "applied twice, others are silently dropped. Finance reports $47K in discrepancies "
            "over the last 2 hours. Additionally, there are unrelated CPU alerts on the "
            "analytics cluster and a cert warning on the CDN. Triage carefully — not everything "
            "is related. Identify ALL root causes and resolve the payment issue."
        ),
        max_steps=25,
        initial_alerts=[
            Alert(
                alert_id="ALT-3001",
                severity="critical",
                service="payment-processor",
                message="Duplicate charge detected: order ORD-88412 charged 2x ($129.99 each)",
                timestamp="2024-01-15T16:30:00Z",
            ),
            Alert(
                alert_id="ALT-3002",
                severity="critical",
                service="payment-processor",
                message="Transaction reconciliation mismatch: 342 transactions missing from ledger",
                timestamp="2024-01-15T16:30:05Z",
            ),
            Alert(
                alert_id="ALT-3003",
                severity="warning",
                service="analytics-cluster",
                message="CPU usage 92% on analytics nodes (batch job running)",
                timestamp="2024-01-15T16:28:00Z",
            ),
            Alert(
                alert_id="ALT-3004",
                severity="warning",
                service="cdn-edge",
                message="TLS certificate expires in 7 days for static.example.com",
                timestamp="2024-01-15T16:00:00Z",
            ),
            Alert(
                alert_id="ALT-3005",
                severity="critical",
                service="payment-db",
                message="Replication lag > 30s between primary and replica-2",
                timestamp="2024-01-15T16:29:00Z",
            ),
            Alert(
                alert_id="ALT-3006",
                severity="warning",
                service="payment-processor",
                message="Retry storm detected: 1,200 retries/min (normal: <10)",
                timestamp="2024-01-15T16:30:30Z",
            ),
        ],
        service_logs={
            "payment-processor": [
                LogEntry(timestamp="2024-01-15T16:25:00Z", level="INFO", service="payment-processor",
                         message="Deployed v3.8.0 — changelog: migrated transactions table to new schema (added idempotency_key column)"),
                LogEntry(timestamp="2024-01-15T16:26:00Z", level="WARN", service="payment-processor",
                         message="Schema migration partial: idempotency_key column exists on primary but NOT on replica-2"),
                LogEntry(timestamp="2024-01-15T16:28:00Z", level="ERROR", service="payment-processor",
                         message="Idempotency check failed: column 'idempotency_key' not found (read from replica-2). Retrying on primary."),
                LogEntry(timestamp="2024-01-15T16:28:01Z", level="ERROR", service="payment-processor",
                         message="Race condition: charge executed on primary BEFORE idempotency check completed on retry"),
                LogEntry(timestamp="2024-01-15T16:28:05Z", level="ERROR", service="payment-processor",
                         message="DUPLICATE CHARGE: txn_id=TXN-9981 already processed. Second charge went through."),
                LogEntry(timestamp="2024-01-15T16:29:00Z", level="ERROR", service="payment-processor",
                         message="Write to ledger failed: replication conflict on transactions table. Row dropped silently."),
                LogEntry(timestamp="2024-01-15T16:29:30Z", level="WARN", service="payment-processor",
                         message="Retry logic hitting both primary and replica inconsistently — idempotency broken"),
            ],
            "payment-db": [
                LogEntry(timestamp="2024-01-15T16:25:30Z", level="INFO", service="payment-db",
                         message="DDL statement applied on primary: ALTER TABLE transactions ADD COLUMN idempotency_key VARCHAR(64)"),
                LogEntry(timestamp="2024-01-15T16:25:35Z", level="ERROR", service="payment-db",
                         message="Replication to replica-2 STALLED: DDL replay failed — insufficient disk space on replica-2"),
                LogEntry(timestamp="2024-01-15T16:26:00Z", level="ERROR", service="payment-db",
                         message="replica-2: disk usage 98.7% (/data volume). Cannot apply pending WAL segments."),
                LogEntry(timestamp="2024-01-15T16:28:00Z", level="WARN", service="payment-db",
                         message="Replication lag replica-2: 180s and growing. Schema divergence detected."),
                LogEntry(timestamp="2024-01-15T16:29:00Z", level="ERROR", service="payment-db",
                         message="Replication conflict: row in transactions written to primary, rejected by replica-2 (schema mismatch)"),
            ],
            "analytics-cluster": [
                LogEntry(timestamp="2024-01-15T16:27:00Z", level="INFO", service="analytics-cluster",
                         message="Daily ETL batch job started. Processing 2.1M events. Expected duration: 45min."),
                LogEntry(timestamp="2024-01-15T16:28:00Z", level="INFO", service="analytics-cluster",
                         message="Batch progress: 34% complete. CPU nominal for workload."),
            ],
            "cdn-edge": [
                LogEntry(timestamp="2024-01-15T16:00:00Z", level="WARN", service="cdn-edge",
                         message="Certificate for static.example.com expires 2024-01-22. Auto-renewal scheduled."),
            ],
            "message-queue": [
                LogEntry(timestamp="2024-01-15T16:29:00Z", level="WARN", service="message-queue",
                         message="payment-events topic: consumer lag 12,000 messages (payment-processor consumer group)"),
                LogEntry(timestamp="2024-01-15T16:29:30Z", level="ERROR", service="message-queue",
                         message="Dead letter queue growing: 342 messages in payment-dlq (unprocessable transactions)"),
            ],
        },
        service_metrics={
            "payment-processor": [
                MetricPoint(name="duplicate_charge_rate", value=3.2, unit="percent", timestamp="2024-01-15T16:30:00Z"),
                MetricPoint(name="transaction_success_rate", value=87.0, unit="percent", timestamp="2024-01-15T16:30:00Z"),
                MetricPoint(name="retry_rate", value=1200.0, unit="per_min", timestamp="2024-01-15T16:30:00Z"),
                MetricPoint(name="idempotency_check_failures", value=890.0, unit="per_min", timestamp="2024-01-15T16:30:00Z"),
                MetricPoint(name="p99_latency", value=8500.0, unit="ms", timestamp="2024-01-15T16:30:00Z"),
            ],
            "payment-db": [
                MetricPoint(name="replication_lag_replica2", value=180.0, unit="seconds", timestamp="2024-01-15T16:29:00Z"),
                MetricPoint(name="disk_usage_replica2", value=98.7, unit="percent", timestamp="2024-01-15T16:26:00Z"),
                MetricPoint(name="active_connections", value=85.0, unit="count", timestamp="2024-01-15T16:30:00Z"),
                MetricPoint(name="write_iops_primary", value=2400.0, unit="iops", timestamp="2024-01-15T16:30:00Z"),
            ],
            "analytics-cluster": [
                MetricPoint(name="cpu_usage", value=92.0, unit="percent", timestamp="2024-01-15T16:28:00Z"),
                MetricPoint(name="batch_progress", value=34.0, unit="percent", timestamp="2024-01-15T16:28:00Z"),
            ],
            "message-queue": [
                MetricPoint(name="consumer_lag", value=12000.0, unit="messages", timestamp="2024-01-15T16:29:00Z"),
                MetricPoint(name="dlq_size", value=342.0, unit="messages", timestamp="2024-01-15T16:29:00Z"),
            ],
        },
        available_commands={
            "rollback payment-processor 3.7.9": "Rolling back payment-processor to v3.7.9 (pre-migration)... OK. Idempotency using old method.",
            "pause payment-processor retries": "Retry mechanism paused. Failed transactions queued for manual review.",
            "fix-replication replica-2": "Attempting to resync replica-2... ERROR: insufficient disk space.",
            "expand-disk replica-2 500GB": "Expanding /data volume on replica-2 to 500GB... OK. Disk usage now 49%.",
            "resync-replication replica-2": "Resyncing replica-2 from primary snapshot... Schema synchronized. Replication lag recovering.",
            "replay-dlq payment-dlq": "Replaying 342 dead letter messages through payment-processor... 340 succeeded, 2 permanently failed.",
            "enable-maintenance payment-processor": "Maintenance mode enabled. New transactions queued, processing paused.",
            "disable-maintenance payment-processor": "Maintenance mode disabled. Processing resumed. Queue draining.",
            "run-reconciliation": "Running transaction reconciliation... Found 342 missing ledger entries. 18 duplicate charges identified. Report generated.",
            "refund-duplicates": "Processing refunds for 18 duplicate charges ($2,339.82 total)... All refunds initiated.",
            "remove-replica replica-2": "Removing replica-2 from read pool... OK. Reads now served by primary + replica-1 only.",
        },
        root_causes=[
            "schema migration",
            "idempotency",
            "replication",
            "replica-2",
            "disk space",
            "deploy v3.8.0",
            "version 3.8.0",
            "bad deploy",
            "schema divergence",
            "replication lag",
            "duplicate charge",
            "idempotency_key",
        ],
        valid_remediations=[
            "rollback",
            "expand-disk",
            "resync-replication",
            "resync replication",
            "remove-replica",
            "pause retries",
            "replay-dlq",
            "refund",
            "reconciliation",
            "maintenance",
        ],
        correct_escalation_teams=["payments", "database", "infrastructure", "finance"],
        relevant_services=["payment-processor", "payment-db", "message-queue"],
        red_herring_services=["analytics-cluster", "cdn-edge"],
        root_cause_categories={
            "deploy_schema": [
                "schema migration", "deploy v3.8.0", "version 3.8.0",
                "bad deploy", "schema divergence", "schema mismatch",
            ],
            "replication_disk": [
                "replication", "replica-2", "disk space", "disk full",
                "replication lag", "replication conflict",
            ],
            "idempotency": [
                "idempotency", "idempotency_key", "duplicate charge",
                "duplicate charges", "retry", "race condition",
            ],
        },
        min_root_cause_categories=2,
    )


SCENARIOS: dict[str, Scenario] = {
    "easy_db_pool": _easy_scenario(),
    "medium_cache_cascade": _medium_scenario(),
    "hard_payment_corruption": _hard_scenario(),
}


def get_scenario(task_id: str) -> Scenario:
    if task_id not in SCENARIOS:
        raise ValueError(f"Unknown task_id: {task_id}. Available: {list(SCENARIOS.keys())}")
    return SCENARIOS[task_id]
