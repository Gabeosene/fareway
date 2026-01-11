# Demo Runbook: Budapest Congestion Control

## Setup
1.  **Environment**: Ensure Python 3.8+ is installed.
2.  **Dependencies**: `pip install fastapi uvicorn rich`
3.  **Files**:
    *   `demo_config.json`: Configuration (Links, Users, Policy).
    *   `manager.py`: Core logic.
    *   `simulate.py`: Scenario driver.

## Execution
Run the interactive CLI demo:
```bash
python simulate.py
```

## Scenario Walkthrough

### Step A: Baseline (Reggel)
*   **Context**: Morning rush hour starts.
*   **Input**: Flow injected at 800/1200 (Széchenyi) and 1000/2500 (Erzsébet).
*   **Expected Output**:
    *   CI ~0.66 (Green/Yellow).
    *   Price matches Base Price (500 HUF).
    *   *János* gets a quote for 500 HUF.

### Step B: The Spike (Dugó)
*   **Event**: "Traffic Accident on Clark Ádám tér".
*   **Input**: Flow spikes to 1150/1200 (95%).
*   **System Action**:
    *   Forecast CI shoots to ~0.95.
    *   Price Multiplier activates.
    *   **New Price**: ~1500 HUF (Red/Surge).

### Step C: Equity Protection
*   **User**: *Eva* (Equity Tier / Student).
*   **Action**: She requests a quote during the surge.
*   **Result**:
    *   System sees `tier='equity'`.
    *   Applies 50% discount to base (or capped) price.
    *   **Price**: ~750 HUF (vs 1500 HUF standard).

### Step D: Behavior Shift
*   **User**: *Zoltán* (Flexible).
*   **Action**: Sees High Price (1500 HUF) vs Metro Option.
*   **Incentive**: Metro M4 is free flowing (CI < 0.2).
*   **Result**:
    *   Metro Price: 450 HUF.
    *   **Reward**: +100 Credits.
    *   Zoltán chooses Metro.

### Step E: Resolution
*   **Simulation**: 500 cars shift to Metro.
*   **Result**:
    *   Széchenyi Flow drops to 650.
    *   Status returns to "FLOWING".
    *   "Gravity Assist" engaged (Easter Egg).
