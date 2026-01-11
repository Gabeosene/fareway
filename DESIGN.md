# From Congestion to Connection: Platform Design

## 1. One-Page Overview

**The Concept:**
A lightweight "digital twin" system that manages traffic demand by creating a feedback loop between **congestion forecasts** and **user incentives**. Instead of rigid tolls, the system publishes dynamic "opportunity costs" or "rewards" to shift behavior in real-time.

**The Story:**
1.  **Congestion:** Traffic is high. The "Twin" detects a bottleneck on the Main Highway.
2.  **Pricing/Incentives:** The system automatically raises the virtual cost for the Main Highway and offers **Rewards Credits** for taking the Scenic Route or Public Transit.
3.  **Behavior Shift:** Users view options via a transparent Quote flow. Some choose the cheaper/rewarded option.
4.  **Better Flow + Equity:** Traffic balances out. Low-income users receive automatic discounts (equity), ensuring the system doesn't punish those who can't pay.

**Glossary:**
*   **Digital Twin:** A simplified in-memory model of the road network that tracks state (flow) and predicts near-term future.
*   **Congestion Index (CI):** A score from 0.0 (empty) to 1.0 (jammed) representing link usage.
*   **Quote/Hold/Confirm:** The transactional flow ensuring a user locks in a price/reward before traveling, preventing "surprise pricing."
*   **Rewards Credits:** Virtual currency earned by helping the network (e.g., traveling off-peak), redeemable for future travel discounts.

---

## 2. Reference Architecture

```text
[   User App / CLI   ]       [   Admin Console   ]
        |                            |
        v                            v
[ D. Quote Service   ]<----->[ C. Policy Engine ]
(State Machine)              (Rules, Discounts)
        |                            ^
        | Price?                     |
        v                            |
[ B. Pricing Engine  ]<----->[ A. Twin/Forecast ]
(Price logic)                (Loop, State, Obs)
        |                            ^
        v                            |
[ F. Telemetry/Analytics ]-->[ Observation Feed ]
```

**Modules (Implemented in `manager.py`):**
*   **A. Twin/Forecast:** Maintains `NetworkLink` state.
*   **B. Pricing Engine:** Calculates `current_price` based on `forecast_ci`.
*   **C. Policy Engine:** Applies `equity_discount` and `reward_credits`.
*   **D. Quote/Reserve/Confirm:** Manages `Quote` and `Reservation` objects.

---

## 3. Data Model

| Entity | Fields | Notes |
| :--- | :--- | :--- |
| **UserProfile** | `id`, `tier`, `balance` | `tier='equity'` triggers 50% discount. |
| **NetworkLink** | `id`, `capacity`, `base_price`, `current_ci` | Static graph + dynamic state. |
| **Quote** | `id`, `final_price`, `rewards`, `expires_at` | Ephemeral offer (30s expiry). |
| **Reservation** | `id`, `status` (HOLD/CONFIRMED), `expires_at` | Locks usage (5m expiry). |

---

## 4. Control Loop ("The Twin")

**Cycle (runs every tick in `simulate.py`):**

1.  **Ingest:** Read Flow.
2.  **Calculate CI:** $CI = Flow / Capacity$.
3.  **Forecast:** Simple persistence ($Forecast = CI$).
4.  **Price Update:**
    *   If $Forecast > 0.85$ (Target), increase price.
    *   Formula: $Price = Base \cdot (1 + (Forecast - Target) \cdot 5)$.

---

## 5. Policy Design

**Equity:**
*   **Rule:** If `UserProfile.tier == 'equity'`, apply 50% discount.
*   **Guardrail:** Applied at Quote generation.

**Rewards:**
*   **Rule:** If `Link.ci < 0.4`, award 100 Credits.
*   **Goal:** Incentivize off-peak or underutilized routes (like Metro M4).

---

## 6. Interfaces

**Primary: REST API (`api.py`)**

*   `POST /observations`: Update Twin state.
*   `GET /network/status`: View dashboard.
*   `POST /quotes`: Get pricing options.
*   `POST /reserve`: Lock a quote.
*   `POST /confirm`: Finalize transaction.

 **Optional: CLI (`simulate.py`)**
*   Interactive dashboard showing the loop in action.
