# Market Valuator Skill

## Overview
This skill implements the valuation logic and clearing calculations to maintain parity between local offline compute resource execution and remote peer token settlement.

## Parity Calculations
* **Local Compute Valuation**: Track wall-clock compute duration (CPU, GPU runtime seconds) and hardware parameters (VRAM, thread count).
* **Token Settlement Parity**: Translate total remote proxy tokens consumed to equivalent local hardware time.
* **Accounting frequency**: Update parity totals at the end of each sub-batch completion.
