# Proxy Broker Skill

## Overview
This skill governs the routing rules, fallback triggers, and connection parameters for securing alternative API tokens or Peer-to-Peer proxy compute streams when local quotas are exhausted.

## Routing Rules
* **Primary Path**: Route through the default local API credential.
* **Pool 1: Rotate alternative keys** if a 429 response is encountered or token level drops below 15%. Select from the alternate multi-tenant credentials.
* **Pool 2: Peer-to-Peer Fallback** if Pool 1 is depleted. Trigger Kademlia DHT node discovery and establish WSS node transport loops.

## Operations
* **Credential timeout limit**: 2000ms.
* **DHT Trigger Depletion Threshold**: 25%.
* **Task Splitting ratio**: 10% balanced sub-batches.
