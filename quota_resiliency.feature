Feature: Project QuidPro Quota API Resiliency and Sandboxing Failsafes

  Scenario: Automated Token Vault Circuit-Breaker Triggering under HTTP 429 Exhaustion
    Given the local token vault has multiple API credentials configured in Pool 1
    And the currently active token key is at capacity limits
    When a developer query is dispatched and returns an HTTP 429 Rate Limit error
    Then the circuit-breaker must intercept the response and blacklist the active key for 300 seconds
    And the Crypto-Router Agent must rotate credentials to an alternate active token key
    And the orchestrator must complete the query execution using the rotated key with a latency of less than 2500ms

  Scenario: TUI Stream Ingestion Overload Rate-Limiting Truncation
    Given the local diagnostics dashboard is running a real-time TUI stream visualization
    And the parent ingestion thread is monitoring inbound chunk-length from peer connections
    When the incoming peer visualization stream bandwidth spikes to exceed 16KB/s
    Then the rate-limiting buffer filter must truncate the display buffer to a maximum of 16KB/s
    And the parent ingestion thread must continue running smoothly without crashing or dropping connection

  Scenario: Micro-Turn Malicious Guest Payload Execution and Container Quarantine
    Given an untrusted guest compute payload is executed inside a gVisor runtime container
    And the cgroupsv2 boundaries are configured with failsafe limits of Memory = 2GB and CPU = 10%
    When the guest payload attempts a malicious memory or CPU boundary breach
    Then the Green Team Sandbox Agent must detect the breach within the container
    And the sandbox boundary guardian must enforce the failsafe freeze limits on the container within 100ms
    And the container must be quarantined with its network link dropped immediately
