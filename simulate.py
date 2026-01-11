import time
import os
import sys
import select
import random
import datetime
from collections import deque

from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.console import Console
from rich.text import Text
from rich import box

import manager
import generator

if os.name == "nt":
    import msvcrt
else:
    msvcrt = None

# --- Configuration ---
REFRESH_RATE = 10 # Hz
LOG_SIZE = 8

# --- State ---
console = Console()
mgr = manager.get_manager("full_city_config.json")
gen = generator.TrafficGenerator()
log_messages = deque(maxlen=LOG_SIZE)

# Global accumulator for diverted traffic so it doesn't vanish instantly
global_diverted_flow = 0.0

def generate_header() -> Panel:
    real_time = datetime.datetime.now().strftime("%H:%M:%S")
    sim_time = gen.get_virtual_time()
    
    # Simple Cycle logic
    hour = int(sim_time.split(':')[0])
    day_phase = "NIGHT"
    if 6 <= hour < 20: day_phase = "DAY"
    
    status = f"System Time: {real_time} | [bold yellow]Sim Time: {sim_time}[/bold yellow] | Cycle: {day_phase} | Mode: AUTO-PILOT"
    return Panel(status, style="bold white on blue", box=box.ROUNDED)

def generate_network_table() -> Table:
    table = Table(title="Live Network Telemetry", box=box.SIMPLE_HEAD, expand=True)
    table.add_column("Link Name")
    table.add_column("Load %", justify="right")
    table.add_column("Flow/Cap", justify="right")
    table.add_column("Price (HUF)", justify="right")
    table.add_column("Diversion Effect", justify="center") # New Column

    for link_id, link in mgr.twin.links.items():
        # Color coding
        ci = link.current_ci
        if ci > 0.9: 
            color = "red"
            status = "CRITICAL"
        elif ci > 0.7:
            color = "yellow"
            status = "CONGESTED"
        else:
            color = "green"
            status = "FLOWING"
            
        load_pct = f"{int(ci * 100)}%"
        flow_fmt = f"{int(link.current_flow)}/{link.capacity}"
        price_fmt = f"{link.current_price} HUF"
        
        # Highlight price if surging
        if link.price_multiplier > 1.2:
            price_fmt = f"[bold red]{price_fmt}[/bold red] (x{link.price_multiplier:.1f})"
            
        # Diversion status - show if cars are leaving/entering due to policy
        div_str = "-"
        if hasattr(link, 'last_diversion'):
            if link.last_diversion > 50:
                div_str = f"[green]↓ {int(link.last_diversion)} diverted[/green]" # Leaving
            elif link.last_diversion < -50:
                 div_str = f"[yellow]↑ {int(abs(link.last_diversion))} captured[/yellow]" # Entering (Metro)

        table.add_row(
            link.name,
            f"[{color}]{load_pct}[/{color}]",
            flow_fmt,
            price_fmt,
            div_str
        )
    return table

def generate_log_panel() -> Panel:
    text = Text()
    for msg in log_messages:
        text.append(msg + "\n")
    return Panel(text, title="Transaction Stream", border_style="cyan", box=box.ROUNDED)

def generate_help_panel() -> Panel:
    return Panel(
        "[bold]A[/bold]: Accident (Chain Bridge)  |  [bold]Q[/bold]: Quit",
        title="Controls",
        border_style="white",
        box=box.ROUNDED
    )

def make_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3)
    )
    layout["body"].split_row(
        Layout(name="left", ratio=2),
        Layout(name="right", ratio=1)
    )
    return layout

def update_layout(layout: Layout):
    layout["header"].update(generate_header())
    layout["left"].update(generate_network_table())
    layout["right"].update(generate_log_panel())
    layout["footer"].update(generate_help_panel())

def calculate_flow_logic():
    now = time.time()
    total_shifting_demand = 0.0
    
    # 1. Calculate Base Demand & Diversion for Roads
    for link_id, link in mgr.twin.links.items():
        # Get raw demand from world generator
        base_demand = gen.get_flow(link_id, link.capacity, now)
        
        # Calculate Diversion if Price is High
        # Simple elasticity: For every 10% price increase, 5% of traffic diverts?
        # Let's be explicit:
        # Base Price = link.base_price
        # Current = link.current_price
        # Multiplier = link.price_multiplier
        
        shifted_flow = 0
        if link.price_multiplier > 1.0:
            # Elasticity factor: How easily do people give up?
            # 1.5x price -> 20% diversion
            excess_p = link.price_multiplier - 1.0
            diversion_pct = excess_p * 0.4 # Tuning: 2.0x price = 40% diversion
            diversion_pct = min(0.9, diversion_pct) # Max 90%
            
            shifted_flow = base_demand * diversion_pct
            
        # Apply
        final_flow = base_demand - shifted_flow
        
        # Store for display
        link.last_diversion = shifted_flow 
        
        # If it's a road, this traffic goes to Metro
        # Ideally check 'type' but let's hardcode for demo: 
        # Chain Bridge (road) -> Metro 4 (transit)
        if "Bridge" in link.name:
            total_shifting_demand += shifted_flow
        else:
            # It's the Metro or others. 
            pass

        link.current_flow = final_flow # Staging, will commit via ingest

    # 2. Add Shifted Demand to Metro
    metro = mgr.twin.links.get("link_m4")
    if metro:
        # The Metro absorbs the traffic!
        metro.current_flow += total_shifting_demand
        metro.last_diversion = -total_shifting_demand # Negative means "Gained"

    # 3. Commit to Twin
    for link_id, link in mgr.twin.links.items():
        mgr.twin.ingest_observation(link_id, link.current_flow)


def simulate_random_user_activity():
    if random.random() < 0.1: # 10% chance per tick
        u_id = random.choice(list(mgr.twin.users.keys()))
        l_id = random.choice(list(mgr.twin.links.keys()))
        
        # Create Quote
        q = mgr.service.create_quote(u_id, l_id)
        
        # Log it
        user_name = mgr.twin.users[u_id].name.split()[0]
        link_name = mgr.twin.links[l_id].name.split()[0]
        msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {user_name} -> {link_name}: {q.final_price} HUF"
        if q.discount_amount > 0:
            msg += f" [green](Saved {q.discount_amount})[/green]"
        log_messages.append(msg)

def main():
    layout = make_layout()
    
    with Live(layout, refresh_per_second=REFRESH_RATE, screen=True) as live:
        try:
            while True:
                # 1. Input
                key = None
                if msvcrt and msvcrt.kbhit():
                    key = msvcrt.getch().decode(errors="ignore").lower()
                else:
                    ready, _, _ = select.select([sys.stdin], [], [], 0)
                    if ready:
                        key = sys.stdin.read(1).lower()

                if key == "q":
                    break
                elif key == "a":
                    gen.trigger_accident("link_szechenyi")
                    log_messages.append("[bold red] ALERT: ACCIDENT REPORTED ON CHAIN BRIDGE![/bold red]")

                # 2. Physics & Logic
                calculate_flow_logic() # <-- New smarter logic
                mgr.twin.tick()
                simulate_random_user_activity()

                # 3. Render
                update_layout(layout)
                time.sleep(1/REFRESH_RATE)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    main()
