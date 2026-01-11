# Debugging Guide: Silent Photon

This guide outlines how to verify the health of the Silent Photon system and troubleshoot common issues.

## 1. Quick Verification (`debug_suite.py`)

We have included a standalone script to verify configuration and core logic without running the web server.

**Run the suite:**
```bash
python debug_suite.py
```

**What it checks:**
1.  **Configuration Integrity**: Ensures `demo_config.json` (or your active config) has all valid fields.
2.  **Pricing Logic**: Simulates a traffic jam to ensure prices increase.
3.  **Policy Logic**: Verifies that Equity users receive their 50% discount.

## 2. Common Issues & Fixes

### "Address already in use"
*   **Symptom**: `OSError: [Errno 98] Address already in use` when starting `server.py`.
*   **Cause**: Another instance of the server is running or the port (8000) is blocked.
*   **Fix**:
    *   Find the process: `netstat -ano | findstr :8000` (Windows) or `lsof -i :8000` (Linux/Mac).
    *   Kill it: `taskkill /PID <PID> /F` (Windows) or `kill <PID>` (Linux/Mac).

### "Simulator running too fast/slow"
*   **Fix**: Use the Admin API to adjust speed.
    *   `POST /sim/control` with `{"action": "SPEED", "speed": 1.0}` to reset to normal.

### "No changes in UI"
*   **Check**: Is the simulation paused?
*   **Fix**: Check `/status` endpoint. If `sim_status` is "PAUSED", send `POST /sim/control` with `{"action": "RESUME"}`.

## 3. Admin Debug APIs

Use these endpoints (via Postman or `curl`) to force state changes for testing.

| Goal | Endpoint | Payload |
| :--- | :--- | :--- |
| **Trigger Accident** | `POST /simulate/accident` | `{"link_id": "L1"}` |
| **Change Weather** | `POST /admin/weather/{type}` | `SUNNY`, `RAIN`, `STORM` |
| **Max Aggression** | `POST /admin/agent/aggressiveness/EXTREME` | N/A |
| **Nudge Sensitivity**| `POST /admin/policy/sensitivity/nudge`| `{"amount": 1.0}` |

## 4. Logs

Monitor the terminal output where `server.py` is running.
-   **[INFO]**: Normal operation.
-   **[WARNING]**: Non-critical issues (e.g., lag in simulation loop).
-   **[ERROR]**: Critical failures detailed in stack traces.
